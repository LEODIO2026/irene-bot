"""실행: python -m unittest paper_terminal.tests.test_terminal -v"""
import unittest

from paper_terminal.config import Config
from paper_terminal.engine import Engine
from paper_terminal.sources import SimClock, SimSource, Snapshot, parse_pair
from paper_terminal.store import Store
from paper_terminal.web import create_app

T0 = 1_800_000_000.0


def snap(token='AAA', **kw):
    base = dict(chain='solana', token=token, pair='P' + token, symbol=token, dex='x', url='',
                price=1.0, liquidity=50_000, fdv=500_000, vol_m5=10_000, vol_h1=24_000,
                buys_m5=60, sells_m5=30, buys_h1=300, sells_h1=200, chg_m5=8.0, chg_h1=20.0,
                created_at=T0 - 3600)
    base.update(kw)
    return Snapshot(**base)


class FakeSource:
    name = 'fake'

    def __init__(self):
        self.snaps, self.ok, self.rug = {}, True, {'score_normalised': 1, 'risks': [], 'lpLockedPct': 100}

    def fetch(self, extra_tokens=()):
        return dict(self.snaps), [], self.ok

    def rug_report(self, token):
        return self.rug


def make(balance=1000.0, **cfg_kw):
    cfg = Config()
    cfg.start_balance = balance
    for k, v in cfg_kw.items():
        setattr(cfg, k, v)
    clock, src = SimClock(T0), FakeSource()
    return Engine(cfg, store=Store(':memory:'), source=src, clock=clock), src, clock


def msgs(eng, agent=None):
    return [e['msg'] for e in eng.store.events(200) if agent in (None, e['agent'])]


class ScannerRugSizer(unittest.TestCase):
    def test_signal_opens_position_with_reasons(self):
        eng, src, _ = make()
        src.snaps = {'AAA': snap()}
        eng.tick()
        (t,) = eng.store.open_trades()
        self.assertIn('5분 거래량', t['entry_reason'])
        self.assertIn('LP 잠금', t['rug_summary'])
        # 손절 15%에 계좌의 2%만 위험 → 1000*0.02/0.15 = 133.33
        self.assertAlmostEqual(t['size_usd'], 133.33, places=2)
        self.assertGreater(t['entry_slip_bps'], 0)
        self.assertGreater(t['entry_price'], t['entry_mid'])        # 슬리피지·수수료만큼 비싸게 삼
        self.assertAlmostEqual(eng.store.get('cash'), 1000 - 133.33 - 0.02, places=2)
        self.assertLess(eng.equity()[0], 1000)                      # 사자마자 비용만큼 자산 감소

    def test_no_signal_without_volume_spike(self):
        eng, src, _ = make()
        src.snaps = {'AAA': snap(vol_m5=3_500, vol_h1=60_000), 'BBB': snap('BBB', buys_m5=10, sells_m5=30),
                     'CCC': snap('CCC', chg_m5=90), 'DDD': snap('DDD', created_at=T0 - 100 * 3600)}
        eng.tick()
        self.assertEqual(eng.store.open_trades(), [])

    def test_rug_blocks(self):
        cases = {
            '유동성 정보 없음': dict(liquidity=0),
            '최소': dict(liquidity=5_000),
            '너무 새로움': dict(created_at=T0 - 120),
            '과대평가': dict(fdv=5_000_000),
            '허니팟': dict(sells_h1=0),
            '덤핑': dict(chg_h1=-70),
        }
        for needle, kw in cases.items():
            eng, src, _ = make()
            src.snaps = {'AAA': snap(**kw)}
            eng.tick()
            self.assertEqual(eng.store.open_trades(), [], needle)
            self.assertTrue(any(needle in m for m in msgs(eng, 'rug')), needle)

    def test_rugcheck_report_blocks(self):
        for rep, needle in [({'risks': [{'name': 'Mint Authority', 'level': 'danger'}], 'score_normalised': 5}, 'Mint Authority'),
                            ({'risks': [], 'score_normalised': 55, 'lpLockedPct': 100}, '위험 점수'),
                            ({'risks': [], 'score_normalised': 1, 'lpLockedPct': 0}, 'LP 잠금'),
                            (None, '조회 실패')]:
            eng, src, _ = make()
            src.rug, src.snaps = rep, {'AAA': snap()}
            eng.tick()
            self.assertEqual(eng.store.open_trades(), [], needle)
            self.assertTrue(any(needle in m for m in msgs(eng, 'rug')), needle)

    def test_sizer_caps_and_skips(self):
        eng, src, _ = make(balance=100_000)        # 풀 유동성의 1% 한도에 걸림
        src.snaps = {'AAA': snap()}
        eng.tick()
        self.assertAlmostEqual(eng.store.open_trades()[0]['size_usd'], 500.0)

        eng, src, _ = make(balance=10)             # 너무 작은 계좌 → 수수료가 더 큼
        src.snaps = {'AAA': snap()}
        eng.tick()
        self.assertEqual(eng.store.open_trades(), [])
        self.assertTrue(any('최소' in m for m in msgs(eng, 'sizer')))

        eng, src, _ = make(max_open_positions=2)
        src.snaps = {k: snap(k) for k in 'ABC'}
        eng.tick()
        self.assertEqual(len(eng.store.open_trades()), 2)

    def test_paused_and_cooldown(self):
        eng, src, clock = make()
        eng.paused = True
        src.snaps = {'AAA': snap()}
        eng.tick()
        self.assertEqual(eng.store.open_trades(), [])
        eng.paused = False
        src.rug = None                              # 차단되면 30분간 다시 보지 않음
        eng.tick(); eng.tick()
        self.assertEqual(len(msgs(eng, 'rug')), 1)


class Exits(unittest.TestCase):
    def _open(self, **cfg):
        eng, src, clock = make(**cfg)
        src.snaps = {'AAA': snap()}
        eng.tick()
        self.assertEqual(len(eng.store.open_trades()), 1)
        return eng, src, clock

    def _closed(self, eng):
        (t,) = eng.store.closed_trades()
        self.assertEqual(eng.store.open_trades(), [])
        return t

    def test_stop_loss(self):
        eng, src, clock = self._open()
        clock.advance(30); src.snaps = {'AAA': snap(price=0.80, chg_m5=-20)}
        eng.tick()
        t = self._closed(eng)
        self.assertIn('손절', t['exit_reason'])
        self.assertLess(t['pnl_usd'], -133.33 * 0.20)               # 가격 하락 + 비용
        self.assertAlmostEqual(eng.store.get('cash'), 1000 + t['pnl_usd'], places=6)
        self.assertAlmostEqual(eng.store.equity_points()[-1]['equity'], 1000 + t['pnl_usd'], places=6)

    def test_take_profit(self):
        eng, src, clock = self._open()
        clock.advance(30); src.snaps = {'AAA': snap(price=1.40)}
        eng.tick()
        t = self._closed(eng)
        self.assertIn('익절', t['exit_reason'])
        self.assertGreater(t['pnl_usd'], 0)
        self.assertLess(t['pnl_usd'], 133.33 * 0.40)                # 비용 때문에 표면 수익보다 작음

    def test_trailing_stop(self):
        eng, src, clock = self._open()
        clock.advance(30); src.snaps = {'AAA': snap(price=1.25)}; eng.tick()
        self.assertEqual(len(eng.store.open_trades()), 1)
        clock.advance(30); src.snaps = {'AAA': snap(price=1.10)}; eng.tick()
        self.assertIn('추적 손절', self._closed(eng)['exit_reason'])

    def test_time_stop(self):
        eng, src, clock = self._open()
        clock.advance(91 * 60); src.snaps = {'AAA': snap(price=1.02, chg_m5=0)}; eng.tick()
        self.assertIn('시간 청산', self._closed(eng)['exit_reason'])

    def test_liquidity_pull_is_near_total_loss(self):
        eng, src, clock = self._open()
        clock.advance(30); src.snaps = {'AAA': snap(price=0.9, liquidity=200)}; eng.tick()
        t = self._closed(eng)
        self.assertIn('유동성 급감', t['exit_reason'])
        self.assertLess(t['pnl_pct'], -40)                          # 풀이 비면 제값에 못 판다

    def test_missing_data_counts_only_when_api_ok(self):
        eng, src, clock = self._open()
        src.snaps, src.ok = {}, False
        for _ in range(10):
            eng.tick()
        self.assertEqual(len(eng.store.open_trades()), 1)           # API 장애는 세지 않음
        src.ok = True
        for _ in range(5):
            eng.tick()
        t = self._closed(eng)
        self.assertIn('전액 손실', t['exit_reason'])
        self.assertAlmostEqual(t['pnl_usd'], -(133.33 + 0.02), places=2)

    def test_halt_after_drawdown(self):
        eng, src, _ = make()
        eng.store.set('cash', 550.0)                                # 시작 대비 -45%
        src.snaps = {'AAA': snap()}
        eng.tick()
        self.assertEqual(eng.store.open_trades(), [])
        self.assertTrue(any('신규 진입 중단' in m for m in msgs(eng, 'sizer')))


class Misc(unittest.TestCase):
    def test_parse_pair_handles_missing_fields(self):
        self.assertIsNone(parse_pair({'baseToken': {'address': 'x'}}))
        s = parse_pair({'chainId': 'solana', 'pairAddress': 'p', 'priceUsd': '0.5', 'baseToken': {'address': 'x', 'symbol': 'X'},
                        'priceChange': {'m5': None}, 'volume': {}, 'pairCreatedAt': 1000})
        self.assertEqual((s.price, s.liquidity, s.chg_m5, s.created_at), (0.5, 0.0, 0.0, 1.0))

    def test_sim_run_keeps_books_consistent(self):
        cfg = Config(); cfg.start_balance = 500.0
        clock = SimClock(T0)
        eng = Engine(cfg, store=Store(':memory:'), source=SimSource(cfg, seed=3, clock=clock), clock=clock)
        for _ in range(1500):
            eng.tick()
        st = eng.state()
        self.assertGreater(st['stats']['trades'], 5)
        closed = eng.store.all_closed()
        open_cost = sum(t['size_usd'] + cfg.network_fee for t in eng.store.open_trades())
        self.assertAlmostEqual(st['cash'], 500 + sum(r['pnl_usd'] for r in closed) - open_cost, places=6)
        self.assertGreaterEqual(st['cash'], 0)
        self.assertTrue(all(t['entry_reason'] and t['exit_reason'] for t in eng.store.closed_trades(1000)))

    def test_web_api(self):
        eng, src, _ = make()
        src.snaps = {'AAA': snap(symbol='<img src=x>')}
        eng.tick()
        c = create_app(eng).test_client()
        st = c.get('/api/state').get_json()
        self.assertEqual(st['mode'], 'PAPER')
        self.assertEqual(len(st['open']), 1)
        self.assertEqual(len(st['agents']), 6)
        self.assertEqual(c.get('/').status_code, 200)
        self.assertTrue(c.post('/api/pause', json={'paused': True}).get_json()['paused'])
        c.post('/api/reset')
        st = c.get('/api/state').get_json()
        self.assertEqual((st['open'], st['equity']), ([], 1000.0))


if __name__ == '__main__':
    unittest.main()
