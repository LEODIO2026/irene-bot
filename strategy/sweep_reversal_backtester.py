"""
스윕 반전(Sweep Reversal) 백테스터 v2
────────────────────────────────────────────────
핵심 가설: "유동성 스윕 + 반전 FVG" 패턴 자체가 방향성을 가짐
           — 4H 오더플로우 없이 킬존 필터만으로 최적화

진입 조건:
  BUY:  SSL 스윕(저점 사냥) → 스윕 이후 bullish FVG → 가격 FVG 진입
  SELL: BSL 스윕(고점 사냥) → 스윕 이후 bearish FVG → 가격 FVG 진입

최적화:
  - 여러 RR 값(1.5 ~ 5.0) 자동 스윕 테스트
  - 킬존 필터 유무 비교
  - 수익률(ROI), 최대 낙폭(MDD) 출력
  - 초기 자본 1000 USDT, 매 거래 고정 리스크 1%
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import defaultdict
from core.ict_engine import ICTEngine
from core.data_fetcher import DataFetcher
from strategy.order_flow_backtester import build_order_flow_states


# ═══════════════════════════════════════════════════════
#  킬존 판별 (UTC 기준)
# ═══════════════════════════════════════════════════════

def is_kill_zone(ts: pd.Timestamp) -> str:
    """UTC 시간으로 킬존 세션 반환. 없으면 ''."""
    h = ts.hour
    if 7  <= h < 10: return 'london'
    if 13 <= h < 16: return 'newyork'
    if 0  <= h < 3:  return 'asia'
    return ''


# ═══════════════════════════════════════════════════════
#  스윕 반전 셋업 감지
# ═══════════════════════════════════════════════════════

def find_sweep_reversal_setups(df_snap: pd.DataFrame, ict_engine) -> list:
    n = len(df_snap)
    if n < 30:
        return []

    sweep_lookback = n - 48
    sweeps   = ict_engine.detect_liquidity_sweeps(df_snap)
    all_fvgs = ict_engine.detect_fvg(df_snap)
    setups   = []

    ssl_sweeps = [s for s in sweeps
                  if s['type'] == 'SSL_sweep' and s['index'] >= sweep_lookback]
    if ssl_sweeps:
        sw_idx = max(s['index'] for s in ssl_sweeps)
        for fvg in all_fvgs:
            if fvg['type'] == 'bullish' and fvg['index'] > sw_idx:
                setups.append({'side': 'buy',
                               'top': fvg['top'], 'bottom': fvg['bottom']})

    bsl_sweeps = [s for s in sweeps
                  if s['type'] == 'BSL_sweep' and s['index'] >= sweep_lookback]
    if bsl_sweeps:
        sw_idx = max(s['index'] for s in bsl_sweeps)
        for fvg in all_fvgs:
            if fvg['type'] == 'bearish' and fvg['index'] > sw_idx:
                setups.append({'side': 'sell',
                               'top': fvg['top'], 'bottom': fvg['bottom']})

    return setups


# ═══════════════════════════════════════════════════════
#  수익률 계산
# ═══════════════════════════════════════════════════════

def calc_equity(trades: list, rr: float,
                initial_capital: float = 1000.0,
                risk_pct: float = 0.01) -> dict:
    """
    고정 리스크(자본의 risk_pct%) 기준 누적 수익률 계산.

    Returns:
        {roi, mdd, final_capital, equity_curve}
    """
    capital    = initial_capital
    peak       = initial_capital
    max_dd     = 0.0
    equity     = [initial_capital]

    for t in trades:
        risk_amt = capital * risk_pct   # 복리 적용
        if t['result'] == 'win':
            capital += risk_amt * rr
        else:   # loss 또는 timeout
            capital -= risk_amt
        capital = max(capital, 0)

        if capital > peak:
            peak = capital
        dd = (peak - capital) / peak * 100
        if dd > max_dd:
            max_dd = dd
        equity.append(capital)

    roi = (capital - initial_capital) / initial_capital * 100
    return {
        'roi':           round(roi, 1),
        'mdd':           round(max_dd, 1),
        'final_capital': round(capital, 2),
        'equity_curve':  equity,
    }


# ═══════════════════════════════════════════════════════
#  핵심 시뮬레이션 (단일 RR + kz_only 옵션)
# ═══════════════════════════════════════════════════════

def simulate(df_15m: pd.DataFrame,
             ict_engine,
             rr: float,
             kz_only: bool = False) -> list:
    """
    거래 목록 반환.  kz_only=True면 킬존 시간대만 진입.
    """
    trades        = []
    current_trade = None

    for i in range(200, len(df_15m)):
        row          = df_15m.iloc[i]
        current_time = row['timestamp']

        # ── 진행 중 거래 체크 ──
        if current_trade is not None:
            side   = current_trade['side']
            sl, tp = current_trade['sl'], current_trade['tp']
            result = None

            if side == 'buy':
                if row['low']    <= sl: result = 'loss'
                elif row['high'] >= tp: result = 'win'
            else:
                if row['high']   >= sl: result = 'loss'
                elif row['low']  <= tp: result = 'win'

            if result is None:
                h = (current_time - current_trade['entry_time']).total_seconds() / 3600
                if h >= 24:
                    result = 'timeout'

            if result:
                current_trade['result'] = result
                trades.append(current_trade)
                current_trade = None
            continue

        # ── 킬존 필터 ──
        kz = is_kill_zone(current_time)
        if kz_only and not kz:
            continue

        # ── 셋업 탐지 ──
        snap   = df_15m.iloc[max(0, i - 100): i + 1]
        price  = float(row['close'])
        setups = find_sweep_reversal_setups(snap, ict_engine)

        for zone in setups:
            if not (zone['bottom'] * 0.999 <= price <= zone['top'] * 1.001):
                continue

            side = zone['side']
            if side == 'buy':
                sl = zone['bottom'] * 0.999
                tp = price + (price - sl) * rr
            else:
                sl = zone['top'] * 1.001
                tp = price - (sl - price) * rr

            sl_pct = abs(price - sl) / price * 100
            if not (0.15 <= sl_pct <= 3.0):
                continue

            current_trade = {
                'side':       side,
                'entry_price': price,
                'sl': sl, 'tp': tp,
                'entry_time': current_time,
                'kz':         kz,
                'result':     None,
            }
            break

    return trades


# ═══════════════════════════════════════════════════════
#  메인 백테스터
# ═══════════════════════════════════════════════════════

class SweepReversalBacktester:
    RR_LIST = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0]

    def __init__(self, symbol: str = 'BTC/USDT',
                 initial_capital: float = 1000.0,
                 risk_pct: float = 0.01):
        self.symbol          = symbol
        self.initial_capital = initial_capital
        self.risk_pct        = risk_pct
        self.ict_engine      = ICTEngine()
        self.fetcher         = DataFetcher()

    def run(self, limit: int = 17520):
        print(f"\n{'═'*70}")
        print(f"🎯 스윕 반전 RR 최적화 백테스트: {self.symbol}  |  1년")
        print(f"   초기자본 {self.initial_capital:.0f} USDT  |  "
              f"고정 리스크 {self.risk_pct*100:.1f}%/거래")
        print(f"{'═'*70}")

        # ── 데이터 수집 (한 번만) ──
        df_15m = self.fetcher.fetch_ohlcv(self.symbol, '15m', limit=limit)
        if df_15m is None:
            print("❌ 데이터 수집 실패"); return

        df_15m = df_15m.copy()
        df_15m['body_size']   = abs(df_15m['close'] - df_15m['open'])
        df_15m['avg_body']    = df_15m['body_size'].rolling(10).mean()
        df_15m['swing_high']  = df_15m['high'].rolling(5, center=True).max()
        df_15m['swing_low']   = df_15m['low'].rolling(5, center=True).min()
        df_15m['roll_max_20'] = df_15m['high'].shift(1).rolling(20).max()
        df_15m['roll_min_20'] = df_15m['low'].shift(1).rolling(20).min()
        print(f"✅ 15m {len(df_15m)}봉 로드 완료\n")

        # ── RR 스윕 테스트 ──
        print(f"{'RR':>5}  {'필터':>8}  {'거래':>5}  {'승률':>6}  "
              f"{'기대값':>7}  {'ROI':>8}  {'MDD':>6}  {'최종자본':>10}")
        print(f"{'─'*70}")

        best_roi   = -999
        best_cfg   = None
        results    = []

        for rr in self.RR_LIST:
            for kz_only, label in [(False, '전체'), (True, '킬존만')]:
                trades = simulate(df_15m, self.ict_engine, rr, kz_only)
                if not trades:
                    continue

                total  = len(trades)
                wins   = sum(1 for t in trades if t['result'] == 'win')
                losses = total - wins
                wr     = wins / total * 100
                ev     = (wins * rr - losses) / total
                eq     = calc_equity(trades, rr,
                                     self.initial_capital, self.risk_pct)

                marker = ' ◀' if eq['roi'] > best_roi else ''
                if eq['roi'] > best_roi:
                    best_roi = eq['roi']
                    best_cfg = (rr, label, trades, eq)

                print(f"{rr:>5.1f}  {label:>8}  {total:>5}회  "
                      f"{wr:>5.1f}%  {ev:>+7.3f}R  "
                      f"{eq['roi']:>+7.1f}%  {eq['mdd']:>5.1f}%  "
                      f"{eq['final_capital']:>10,.0f}U{marker}")

                results.append({
                    'rr': rr, 'label': label, 'total': total,
                    'wr': wr, 'ev': ev, **eq,
                })

        # ── 최적 설정 상세 결과 ──
        if best_cfg:
            rr, label, trades, eq = best_cfg
            self._print_detail(trades, rr, label, eq)

    def _print_detail(self, trades, rr, label, eq):
        print(f"\n{'═'*70}")
        print(f"★ 최고 ROI 설정: RR {rr}:1  |  {label}")
        print(f"  ROI {eq['roi']:+.1f}%  |  MDD {eq['mdd']:.1f}%  "
              f"|  최종자본 {eq['final_capital']:,.0f} USDT")
        print(f"{'═'*70}")

        total  = len(trades)
        wins   = sum(1 for t in trades if t['result'] == 'win')
        losses = total - wins
        touts  = sum(1 for t in trades if t['result'] == 'timeout')

        print(f"\n  거래  : {total}회")
        print(f"  승/패 : {wins}승  {losses}패  (타임아웃 {touts}회 포함)")
        print(f"  승률  : {wins/total*100:.1f}%")
        print(f"  기대값: {(wins*rr - losses)/total:+.3f}R")

        # 방향별
        buy_t  = [t for t in trades if t['side'] == 'buy']
        sell_t = [t for t in trades if t['side'] == 'sell']
        def wr_str(ts):
            if not ts: return '없음'
            w = sum(1 for t in ts if t['result'] == 'win')
            eq2 = calc_equity(ts, rr, self.initial_capital, self.risk_pct)
            return (f"{len(ts)}회  승률 {w/len(ts)*100:.1f}%  "
                    f"ROI {eq2['roi']:+.1f}%")
        print(f"\n  SSL스윕 BUY : {wr_str(buy_t)}")
        print(f"  BSL스윕 SELL: {wr_str(sell_t)}")

        # 킬존별 (전체 필터 선택된 경우)
        if label == '전체':
            kz_t   = [t for t in trades if t['kz']]
            nokz_t = [t for t in trades if not t['kz']]
            print(f"\n  킬존 내 : {wr_str(kz_t)}")
            print(f"  킬존 외 : {wr_str(nokz_t)}")

        # 월별
        print(f"\n  {'월':>8}  {'거래':>5}  {'승률':>6}  {'월ROI':>8}")
        monthly = defaultdict(lambda: {'trades': []})
        for t in trades:
            monthly[t['entry_time'].strftime('%Y-%m')]['trades'].append(t)

        for m in sorted(monthly):
            mt   = monthly[m]['trades']
            mw   = sum(1 for t in mt if t['result'] == 'win')
            meq  = calc_equity(mt, rr, self.initial_capital, self.risk_pct)
            print(f"  {m}  {len(mt):>5}회  {mw/len(mt)*100:>5.1f}%  {meq['roi']:>+7.1f}%")

        print(f"{'═'*70}")


if __name__ == '__main__':
    bt = SweepReversalBacktester(symbol='BTC/USDT',
                                  initial_capital=1000.0,
                                  risk_pct=0.01)
    bt.run(limit=17520)
