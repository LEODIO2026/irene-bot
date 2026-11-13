"""여섯 에이전트. 각자 한 가지 일만 한다.

스캐너 → 러그 체크 → 사이저 → 실행기 → (로거, 수익 곡선)
"""
from dataclasses import dataclass


class Agent:
    key = ''
    title = ''
    job = ''

    def __init__(self):
        self.status = '대기 중'
        self.last_ts = None
        self.count = 0

    def note(self, now, status, bump=0):
        self.status, self.last_ts = status, now
        self.count += bump

    def view(self):
        return dict(key=self.key, title=self.title, job=self.job,
                    status=self.status, last_ts=self.last_ts, count=self.count)


# ─────────────────────────── 5. 로거 ───────────────────────────
class Logger(Agent):
    key, title, job = 'logger', '로거', '모든 판단과 거래의 이유를 기록'

    def __init__(self, store):
        super().__init__()
        self.store = store

    def log(self, now, agent, level, symbol, msg, data=None):
        self.store.add_event(now, agent, level, symbol, msg, data)
        self.note(now, f'{agent}: {msg}'[:90], bump=1)


# ─────────────────────────── 1. 스캐너 ───────────────────────────
@dataclass
class Candidate:
    snap: object
    reason: str


class Scanner(Agent):
    key, title, job = 'scanner', '스캐너', '신규 페어와 거래량 급증 탐지'

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def scan(self, now, snaps, skip_tokens):
        c, out = self.cfg, []
        for s in snaps.values():
            if s.token in skip_tokens:
                continue
            if s.age_minutes(now) > c.max_pair_age_hours * 60:
                continue
            avg5 = s.vol_h1 / 12 if s.vol_h1 else 0
            if s.vol_m5 < c.min_vol_m5 or s.vol_m5 < avg5 * c.vol_spike_mult:
                continue
            ratio = s.buys_m5 / max(1, s.sells_m5)
            if ratio < c.min_buy_sell_ratio:
                continue
            if not (c.min_chg_m5 <= s.chg_m5 <= c.max_chg_m5):
                continue
            mult = s.vol_m5 / avg5 if avg5 else 0
            out.append(Candidate(s, (
                f'5분 거래량 ${s.vol_m5:,.0f} (1시간 평균의 {mult:.1f}배), '
                f'매수/매도 {s.buys_m5}/{s.sells_m5}건, 5분 가격 {s.chg_m5:+.1f}%')))
        out.sort(key=lambda x: -x.snap.vol_m5)
        self.note(now, f'{len(snaps)}개 토큰 확인 → 신호 {len(out)}개', bump=len(out))
        return out


# ─────────────────────────── 2. 러그 체크 ───────────────────────────
class RugCheck(Agent):
    key, title, job = 'rug', '러그 체크', '의심스러운 토큰을 진입 전에 차단'

    def __init__(self, cfg, source):
        super().__init__()
        self.cfg, self.source = cfg, source
        self.passed = 0

    def check(self, now, s):
        """(통과 여부, 이유) 반환. 값싼 검사부터 하고 외부 조회는 마지막에."""
        ok, why = self._check(now, s)
        self.passed += ok
        self.note(now, f'{s.symbol}: {"통과" if ok else "차단"} — {why}'[:90], bump=0 if ok else 1)
        return ok, why

    def _check(self, now, s):
        c = self.cfg
        if s.liquidity <= 0:
            return False, '유동성 정보 없음 (본딩커브 단계) — 팔 수 있을지 알 수 없음'
        if s.liquidity < c.min_liquidity:
            return False, f'유동성 ${s.liquidity:,.0f} < 최소 ${c.min_liquidity:,.0f}'
        if s.age_minutes(now) < c.min_pair_age_minutes:
            return False, f'생성 {s.age_minutes(now):.0f}분 — 너무 새로움 (최소 {c.min_pair_age_minutes:.0f}분)'
        if s.fdv and s.fdv / s.liquidity > c.max_fdv_liq_ratio:
            return False, f'시총/유동성 {s.fdv / s.liquidity:.0f}배 — 유동성 대비 과대평가'
        if s.buys_h1 >= 20 and s.sells_h1 == 0:
            return False, f'1시간 매수 {s.buys_h1}건인데 매도 0건 — 허니팟 의심'
        if s.chg_h1 <= -50:
            return False, f'1시간 {s.chg_h1:.0f}% 폭락 — 이미 덤핑됨'
        rep = self.source.rug_report(s.token)
        if rep is None:
            if c.rug_fail_closed:
                return False, 'RugCheck 조회 실패 — 확인 못 하면 사지 않음'
            return True, '기본 검사 통과 (RugCheck 조회 실패)'
        danger = [r.get('name', '?') for r in rep.get('risks') or [] if r.get('level') == 'danger']
        if danger:
            return False, 'RugCheck 위험 항목: ' + ', '.join(danger[:3])
        score = rep.get('score_normalised')
        if score is not None and score > c.max_rug_score:
            return False, f'RugCheck 위험 점수 {score} > 허용 {c.max_rug_score:.0f}'
        lp = rep.get('lpLockedPct')
        if lp is not None and lp < c.min_lp_locked_pct:
            return False, f'LP 잠금 {lp:.0f}% < 최소 {c.min_lp_locked_pct:.0f}% — 유동성 회수 가능'
        return True, (f'유동성 ${s.liquidity:,.0f}, 위험 점수 {score if score is not None else "-"}, '
                      f'LP 잠금 {lp:.0f}%' if lp is not None else f'유동성 ${s.liquidity:,.0f}, 위험 항목 없음')


# ─────────────────────────── 3. 사이저 ───────────────────────────
class Sizer(Agent):
    key, title, job = 'sizer', '사이저', '계좌 잔고에 비례해 포지션 크기 결정'

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def size(self, now, s, equity, cash, n_open, start_balance):
        """(금액, 이유). 금액이 0이면 진입하지 않는다."""
        c = self.cfg
        if equity <= start_balance * (1 - c.halt_drawdown):
            return self._skip(now, s, f'계좌가 시작 대비 -{c.halt_drawdown:.0%} 이하 — 신규 진입 중단')
        if n_open >= c.max_open_positions:
            return self._skip(now, s, f'보유 포지션 {n_open}개 — 최대 {c.max_open_positions}개')
        by_risk = equity * c.risk_per_trade / c.stop_loss
        limits = {
            f'손절 시 계좌의 {c.risk_per_trade:.0%}만 잃도록': by_risk,
            f'계좌의 {c.max_position_pct:.0%} 한도': equity * c.max_position_pct,
            f'풀 유동성의 {c.max_pool_pct:.0%} 한도': s.liquidity * c.max_pool_pct,
            '남은 현금 한도': cash - c.network_fee,
        }
        label, amount = min(limits.items(), key=lambda kv: kv[1])
        if amount < c.min_ticket:
            return self._skip(now, s, f'계산된 크기 ${max(amount, 0):.2f} < 최소 ${c.min_ticket:.2f} — 수수료가 더 큼')
        why = f'자산 ${equity:,.2f} 기준 ${amount:,.2f} ({label})'
        self.note(now, f'{s.symbol}: {why}'[:90], bump=1)
        return round(amount, 2), why

    def _skip(self, now, s, why):
        self.note(now, f'{s.symbol}: 건너뜀 — {why}'[:90])
        return 0.0, why


# ─────────────────────────── 4. 실행기 ───────────────────────────
class Executor(Agent):
    """가상 체결. 실제 주문은 어디로도 나가지 않는다.

    비용 모델: AMM(x*y=k) 가격 충격 + DEX 수수료 + 건당 네트워크 수수료.
    """
    key, title, job = 'executor', '실행기', '가상 매수·매도와 슬리피지 추적'

    def __init__(self, cfg, store):
        super().__init__()
        self.cfg, self.store = cfg, store

    def _impact(self, usd, liquidity):
        reserve = max(liquidity / 2, 1e-9)   # 풀의 절반이 상대 자산
        return usd / (reserve + usd)

    def sell_value(self, qty, price, liquidity):
        """지금 팔면 손에 쥐는 금액과 슬리피지(bps), 수수료."""
        gross = qty * price
        if gross <= 0 or liquidity <= 0:
            return 0.0, 10000.0, 0.0
        impact = self._impact(gross, liquidity)
        after = gross * (1 - impact)
        fee = after * self.cfg.dex_fee + self.cfg.network_fee
        return max(after - fee, 0.0), impact * 1e4, fee

    def open(self, now, s, size_usd, entry_reason, rug_summary, size_reason):
        impact = self._impact(size_usd, s.liquidity)
        fee = size_usd * self.cfg.dex_fee + self.cfg.network_fee
        qty = size_usd * (1 - self.cfg.dex_fee) * (1 - impact) / s.price
        entry_price = size_usd / qty
        cash = self.store.get('cash') - size_usd - self.cfg.network_fee
        self.store.set('cash', cash)
        tid = self.store.insert_trade(dict(
            status='open', chain=s.chain, token=s.token, pair=s.pair, symbol=s.symbol, url=s.url,
            opened_at=now, entry_mid=s.price, entry_price=entry_price, qty=qty, size_usd=size_usd,
            entry_slip_bps=impact * 1e4, entry_fee=fee, entry_liq=s.liquidity,
            entry_reason=entry_reason, rug_summary=rug_summary, size_reason=size_reason,
            peak_price=s.price, last_price=s.price, last_liq=s.liquidity, missing=0))
        self.note(now, f'{s.symbol} 가상 매수 ${size_usd:.2f} (슬리피지 {impact * 1e4:.0f}bps)', bump=1)
        return tid, impact * 1e4

    def exit_reason(self, now, t, s):
        """청산해야 하면 이유 문자열, 아니면 None."""
        c = self.cfg
        gain = s.price / t['entry_mid'] - 1
        peak = max(t['peak_price'], s.price)
        if s.liquidity < t['entry_liq'] * (1 - c.liq_drop_exit):
            return f'유동성 급감 (${t["entry_liq"]:,.0f} → ${s.liquidity:,.0f}) — 러그 의심, 긴급 청산'
        if gain <= -c.stop_loss:
            return f'손절: 진입가 대비 {gain:+.1%} (기준 -{c.stop_loss:.0%})'
        if gain >= c.take_profit:
            return f'익절: 진입가 대비 {gain:+.1%} (목표 +{c.take_profit:.0%})'
        if peak / t['entry_mid'] - 1 >= c.trail_arm and s.price <= peak * (1 - c.trail_gap):
            return f'추적 손절: 고점 대비 {s.price / peak - 1:+.1%} (고점 수익 {peak / t["entry_mid"] - 1:+.1%})'
        if now - t['opened_at'] >= c.max_hold_minutes * 60:
            return f'시간 청산: {c.max_hold_minutes:.0f}분 보유, 현재 {gain:+.1%}'
        return None

    def close(self, now, t, price, liquidity, reason):
        proceeds, slip, fee = self.sell_value(t['qty'], price, liquidity)
        cost = t['size_usd'] + self.cfg.network_fee
        pnl = proceeds - cost
        self.store.set('cash', self.store.get('cash') + proceeds)
        self.store.update_trade(
            t['id'], status='closed', closed_at=now, exit_mid=price,
            exit_price=proceeds / t['qty'] if t['qty'] else 0, exit_slip_bps=slip, exit_fee=fee,
            proceeds=proceeds, pnl_usd=pnl, pnl_pct=pnl / cost * 100, exit_reason=reason,
            last_price=price, last_liq=liquidity)
        self.note(now, f'{t["symbol"]} 가상 매도 {pnl:+.2f}$ (슬리피지 {slip:.0f}bps)', bump=1)
        return pnl, slip


# ─────────────────────────── 6. 수익 곡선 ───────────────────────────
class EquityCurve(Agent):
    key, title, job = 'equity', '수익 곡선', '거래가 끝날 때마다 자산 곡선 갱신'

    def __init__(self, store):
        super().__init__()
        self.store = store

    def record(self, now, equity, cash, note):
        self.store.add_equity(now, equity, cash, note)
        self.note(now, f'자산 ${equity:,.2f} 기록 ({note})'[:90], bump=1)

    def stats(self, start_balance):
        rows = self.store.all_closed()
        wins = [r for r in rows if r['pnl_usd'] > 0]
        peak, max_dd = start_balance, 0.0
        for p in self.store.equity_points():
            peak = max(peak, p['equity'])
            if peak > 0:
                max_dd = max(max_dd, 1 - p['equity'] / peak)
        return dict(
            trades=len(rows), wins=len(wins),
            win_rate=len(wins) / len(rows) * 100 if rows else None,
            realized=sum(r['pnl_usd'] for r in rows),
            fees=sum((r['entry_fee'] or 0) + (r['exit_fee'] or 0) for r in rows),
            max_drawdown=max_dd * 100)
