"""여섯 에이전트를 한 바퀴씩 돌리는 엔진."""
import threading
import time
import traceback

from .agents import EquityCurve, Executor, Logger, RugCheck, Scanner, Sizer
from .sources import DexScreenerSource, SimSource
from .store import Store


def make_source(cfg, clock=time.time):
    return SimSource(cfg, clock=clock) if cfg.source == 'sim' else DexScreenerSource(cfg, clock=clock)


class Engine:
    def __init__(self, cfg, store=None, source=None, clock=time.time):
        self.cfg = cfg
        self.clock = clock
        self.store = store or Store(cfg.db_path)
        self.source = source or make_source(cfg, clock)
        self.logger = Logger(self.store)
        self.scanner = Scanner(cfg)
        self.rug = RugCheck(cfg, self.source)
        self.sizer = Sizer(cfg)
        self.executor = Executor(cfg, self.store)
        self.curve = EquityCurve(self.store)
        self.agents = [self.scanner, self.rug, self.sizer, self.executor, self.logger, self.curve]
        self.cooldown = {}      # token -> 다시 볼 수 있는 시각
        self.paused = False
        self.ticks = 0
        self.last_tick = None
        self.last_error = None
        self.tick_lock = threading.Lock()
        self._init_account()

    # ── 계좌 ──
    def _init_account(self):
        if self.store.get('cash') is None:
            now = self.clock()
            self.store.set('cash', self.cfg.start_balance)
            self.store.set('start_balance', self.cfg.start_balance)
            self.store.set('started_at', now)
            self.curve.record(now, self.cfg.start_balance, self.cfg.start_balance, '시작')
            self.logger.log(now, 'system', 'info', '', f'모의 계좌 개설: 가상 잔고 ${self.cfg.start_balance:,.2f} (실제 돈 아님)')

    @property
    def start_balance(self):
        return self.store.get('start_balance', self.cfg.start_balance)

    def equity(self):
        """현금 + 보유 포지션을 '지금 팔았을 때' 받는 금액."""
        cash = self.store.get('cash')
        held = sum(self.executor.sell_value(t['qty'], t['last_price'], t['last_liq'])[0]
                   for t in self.store.open_trades())
        return cash + held, cash

    def reset(self):
        with self.tick_lock:
            self.store.reset()
            self.cooldown.clear()
            for a in self.agents:
                a.status, a.last_ts, a.count = '대기 중', None, 0
            self.rug.passed = 0
            self._init_account()

    # ── 한 바퀴 ──
    def tick(self):
        with self.tick_lock:
            opens = self.store.open_trades()
            snaps, errors, ok = self.source.fetch(extra_tokens=[t['token'] for t in opens])
            now = self.clock()
            for e in errors[:2]:
                self.logger.log(now, 'scanner', 'warn', '', f'데이터 수집 오류: {e}'[:200])

            self._manage(now, opens, snaps, ok)
            if not self.paused:
                self._enter(now, snaps)
            self.ticks += 1
            self.last_tick = now

    def _manage(self, now, opens, snaps, ok):
        for t in opens:
            s = snaps.get(t['token'])
            if s is None:
                if not ok:
                    continue   # API 장애일 뿐일 수 있으니 세지 않는다
                missing = t['missing'] + 1
                self.store.update_trade(t['id'], missing=missing)
                if missing >= self.cfg.missing_polls_exit:
                    self._close(now, t, 0.0, 0.0, f'{missing}회 연속 시세 없음 — 러그/상장폐지로 보고 전액 손실 처리')
                continue
            reason = self.executor.exit_reason(now, t, s)
            self.store.update_trade(t['id'], last_price=s.price, last_liq=s.liquidity, missing=0,
                                    peak_price=max(t['peak_price'], s.price))
            if reason:
                self._close(now, t, s.price, s.liquidity, reason)

    def _close(self, now, t, price, liquidity, reason):
        pnl, slip = self.executor.close(now, t, price, liquidity, reason)
        self.cooldown[t['token']] = now + self.cfg.cooldown_minutes * 60
        self.logger.log(now, 'executor', 'win' if pnl > 0 else 'loss', t['symbol'],
                        f'매도 {pnl:+.2f}$ — {reason}', dict(trade_id=t['id'], slip_bps=round(slip)))
        equity, cash = self.equity()
        self.curve.record(now, equity, cash, f'{t["symbol"]} 청산 {pnl:+.2f}$')

    def _enter(self, now, snaps):
        held = {t['token'] for t in self.store.open_trades()}
        cooling = {k for k, until in self.cooldown.items() if until > now}
        for cand in self.scanner.scan(now, snaps, held | cooling):
            s = cand.snap
            self.cooldown[s.token] = now + self.cfg.cooldown_minutes * 60
            self.logger.log(now, 'scanner', 'info', s.symbol, f'신호 포착 — {cand.reason}')
            ok, why = self.rug.check(now, s)
            if not ok:
                self.logger.log(now, 'rug', 'block', s.symbol, f'차단 — {why}')
                continue
            self.logger.log(now, 'rug', 'info', s.symbol, f'통과 — {why}')
            equity, cash = self.equity()
            size, size_why = self.sizer.size(now, s, equity, cash, len(self.store.open_trades()), self.start_balance)
            if size <= 0:
                self.logger.log(now, 'sizer', 'skip', s.symbol, f'건너뜀 — {size_why}')
                continue
            self.logger.log(now, 'sizer', 'info', s.symbol, size_why)
            tid, slip = self.executor.open(now, s, size, cand.reason, why, size_why)
            self.logger.log(now, 'executor', 'buy', s.symbol,
                            f'매수 ${size:.2f} @ ${s.price:.8g} (슬리피지 {slip:.0f}bps) — {cand.reason}',
                            dict(trade_id=tid))

    # ── 반복 실행 ──
    def run_forever(self):
        while True:
            try:
                self.tick()
                self.last_error = None
            except Exception as e:
                self.last_error = str(e)
                traceback.print_exc()
            time.sleep(self.cfg.poll_seconds)

    # ── 대시보드용 상태 ──
    def state(self):
        equity, cash = self.equity()
        start = self.start_balance
        opens = []
        for t in self.store.open_trades():
            value = self.executor.sell_value(t['qty'], t['last_price'], t['last_liq'])[0]
            cost = t['size_usd'] + self.cfg.network_fee
            opens.append(dict(t, value=value, pnl_usd=value - cost, pnl_pct=(value - cost) / cost * 100))
        return dict(
            now=self.clock(), mode='PAPER', source=self.source.name, simulated=getattr(self.source, 'simulated', False), paused=self.paused,
            ticks=self.ticks, last_tick=self.last_tick, last_error=self.last_error,
            poll_seconds=self.cfg.poll_seconds, started_at=self.store.get('started_at'),
            start_balance=start, equity=equity, cash=cash,
            pnl_usd=equity - start, pnl_pct=(equity / start - 1) * 100 if start else 0,
            stats=self.curve.stats(start), rug_passed=self.rug.passed,
            agents=[a.view() for a in self.agents],
            open=opens, closed=self.store.closed_trades(50),
            events=self.store.events(80), curve=self.store.equity_points())
