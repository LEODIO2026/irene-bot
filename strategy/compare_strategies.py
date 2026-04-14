"""
전략 비교 백테스터
────────────────────────────────────────────────
동일 조건으로 4가지 전략을 한눈에 비교:

  A. 위성 전략 v3  (1D BOS/MSS + 200EMA + 4H EMA + 킬존 + 스윕 + FVG)
  B. 오더플로우 WITH  (4H 오더플로우 확정 + 방향 일치 스윕 + FVG)
  C. 스윕 반전 전체  (필터 없음)
  D. 스윕 반전 킬존  (킬존 필터만)

공통 조건:
  - 심볼: BTC/USDT
  - 기간: 1년 (15m 17520봉)
  - RR: 3:1 고정
  - SL: FVG 상단/하단 기준
  - SL 범위: 0.15% ~ 3.0%
  - 24H 타임스탑
  - 초기 자본 1000 USDT / 매 거래 고정 리스크 1% (복리 없음)
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import defaultdict
from core.ict_engine import ICTEngine
from core.data_fetcher import DataFetcher
from strategy.order_flow_backtester import build_order_flow_states
from strategy.sweep_reversal_backtester import (
    find_sweep_reversal_setups, is_kill_zone, calc_equity
)


RR              = 3.0
INITIAL_CAPITAL = 1000.0
RISK_PCT        = 0.01    # 1%


# ═══════════════════════════════════════════════════════
#  공통: 진행 중 거래 체크
# ═══════════════════════════════════════════════════════

def check_trade(current_trade, row, rr):
    """현재 봉에서 거래 결과 판정. 결과가 나면 result 키를 채운다."""
    if current_trade is None:
        return None
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
        h = (row['timestamp'] - current_trade['entry_time']).total_seconds() / 3600
        if h >= 24:
            result = 'timeout'

    if result:
        current_trade['result'] = result
        return current_trade
    return None


def make_trade(side, zone, price, current_time, rr, extra=None):
    """FVG 존으로 거래 dict 생성. sl_pct 범위 벗어나면 None."""
    if side == 'buy':
        sl = zone['bottom'] * 0.999
        tp = price + (price - sl) * rr
    else:
        sl = zone['top'] * 1.001
        tp = price - (sl - price) * rr

    sl_pct = abs(price - sl) / price * 100
    if not (0.15 <= sl_pct <= 3.0):
        return None

    t = {
        'side': side, 'entry_price': price,
        'sl': sl, 'tp': tp,
        'entry_time': current_time,
        'result': None,
    }
    if extra:
        t.update(extra)
    return t


# ═══════════════════════════════════════════════════════
#  전략 A: 위성 전략 v3 핵심 (순수 진입 조건)
# ═══════════════════════════════════════════════════════

def simulate_satellite(df_15m, df_4h, df_1d, ict_engine, rr=RR):
    """
    진입 조건:
      1. 킬존 내 (뉴욕 런치 제외)
      2. 1D BOS/MSS → struct_1d 확정
      3. 200 EMA 아래서 BUY 불가
      4. 4H 20 EMA 방향 == struct_1d
      5. 15m 방향 맞는 스윕 존재
      6. 스윕 후 FVG 진입
    """
    trades        = []
    current_trade = None
    h4_idx = d1_idx = 0

    for i in range(200, len(df_15m)):
        row          = df_15m.iloc[i]
        current_time = row['timestamp']

        while h4_idx + 1 < len(df_4h) and df_4h.iloc[h4_idx+1]['timestamp'] <= current_time:
            h4_idx += 1
        while d1_idx + 1 < len(df_1d) and df_1d.iloc[d1_idx+1]['timestamp'] <= current_time:
            d1_idx += 1

        # 진행 중 거래
        done = check_trade(current_trade, row, rr)
        if done:
            trades.append(done)
            current_trade = None
            continue
        if current_trade:
            continue

        # ① 킬존
        kz = is_kill_zone(current_time)
        if not kz or kz == 'newyork_lunch':
            continue

        # ② 1D BOS/MSS
        snap_1d = df_1d.iloc[max(0, d1_idx - 49): d1_idx + 1]
        if len(snap_1d) < 20:
            continue
        bos = ict_engine.detect_bos_mss(snap_1d, swing_window=3)
        struct_1d = bos['direction']
        if struct_1d == 'neutral':
            continue

        # ③ 200 EMA 필터
        ema200 = snap_1d['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        price_now = float(row['close'])
        if price_now < ema200 and struct_1d == 'bullish':
            continue

        # ④ 4H 20 EMA 모멘텀
        snap_4h = df_4h.iloc[max(0, h4_idx - 49): h4_idx + 1]
        if len(snap_4h) < 20:
            continue
        ema20_4h  = snap_4h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        price_4h  = float(snap_4h['close'].iloc[-1])
        mom_4h    = 'bullish' if price_4h > ema20_4h else 'bearish'
        if mom_4h != struct_1d:
            continue

        side = 'buy' if struct_1d == 'bullish' else 'sell'

        # ⑤⑥ 스윕 후 FVG
        snap_15m = df_15m.iloc[max(0, i - 100): i + 1]
        setups   = find_sweep_reversal_setups(snap_15m, ict_engine)
        for z in setups:
            if z['side'] != side:
                continue
            if not (z['bottom'] * 0.999 <= price_now <= z['top'] * 1.001):
                continue
            t = make_trade(side, z, price_now, current_time, rr)
            if t:
                current_trade = t
                break

    return trades


# ═══════════════════════════════════════════════════════
#  전략 B: 오더플로우 WITH
# ═══════════════════════════════════════════════════════

def simulate_of_with(df_15m, df_4h, ict_engine, of_states, rr=RR):
    trades        = []
    current_trade = None
    h4_idx        = 0

    for i in range(200, len(df_15m)):
        row          = df_15m.iloc[i]
        current_time = row['timestamp']

        while h4_idx + 1 < len(df_4h) and df_4h.iloc[h4_idx+1]['timestamp'] <= current_time:
            h4_idx += 1

        done = check_trade(current_trade, row, rr)
        if done:
            trades.append(done)
            current_trade = None
            continue
        if current_trade:
            continue

        of_dir = of_states[h4_idx]
        if of_dir == 'neutral':
            continue

        snap  = df_15m.iloc[max(0, i - 100): i + 1]
        price = float(row['close'])
        setups = find_sweep_reversal_setups(snap, ict_engine)

        for z in setups:
            side = z['side']
            with_flow = (side == 'buy' and of_dir == 'bullish') or \
                        (side == 'sell' and of_dir == 'bearish')
            if not with_flow:
                continue
            if not (z['bottom'] * 0.999 <= price <= z['top'] * 1.001):
                continue
            t = make_trade(side, z, price, current_time, rr)
            if t:
                current_trade = t
                break

    return trades


# ═══════════════════════════════════════════════════════
#  전략 C/D: 스윕 반전 (필터 없음 / 킬존만)
# ═══════════════════════════════════════════════════════

def simulate_sweep(df_15m, ict_engine, rr=RR, kz_only=False):
    from strategy.sweep_reversal_backtester import simulate
    return simulate(df_15m, ict_engine, rr, kz_only)


# ═══════════════════════════════════════════════════════
#  결과 출력 유틸
# ═══════════════════════════════════════════════════════

def strategy_stats(trades, rr, label, initial_capital=INITIAL_CAPITAL, risk_pct=RISK_PCT):
    if not trades:
        return {'label': label, 'n': 0, 'wr': 0, 'ev': 0,
                'roi': 0, 'mdd': 0, 'final': initial_capital}

    n      = len(trades)
    wins   = sum(1 for t in trades if t['result'] == 'win')
    losses = n - wins
    wr     = wins / n * 100
    ev     = (wins * rr - losses) / n
    eq     = calc_equity(trades, rr, initial_capital, risk_pct)

    return {
        'label': label, 'n': n, 'wins': wins, 'losses': losses,
        'wr': wr, 'ev': ev,
        'roi': eq['roi'], 'mdd': eq['mdd'], 'final': eq['final_capital'],
        'trades': trades, 'equity': eq['equity_curve'],
    }


def print_comparison(results):
    print(f"\n{'═'*80}")
    print(f"  {'전략':<30} {'거래':>5}  {'승률':>6}  {'기대값':>7}  {'ROI':>8}  {'MDD':>6}  {'최종자본':>10}")
    print(f"  {'─'*78}")

    best_roi = max(r['roi'] for r in results)
    for r in results:
        marker = ' ◀ 최고' if r['roi'] == best_roi else ''
        print(f"  {r['label']:<30} {r['n']:>5}회  {r['wr']:>5.1f}%  "
              f"{r['ev']:>+7.3f}R  {r['roi']:>+7.1f}%  {r['mdd']:>5.1f}%  "
              f"{r['final']:>9,.0f}U{marker}")

    print(f"{'═'*80}")

    # 최고 ROI 전략 월별
    best = max(results, key=lambda r: r['roi'])
    if best.get('trades'):
        print(f"\n★ 최고 전략 [{best['label']}] 월별 수익률")
        print(f"  {'월':>8}  {'거래':>5}  {'승률':>6}  {'월ROI':>8}")
        monthly = defaultdict(list)
        for t in best['trades']:
            monthly[t['entry_time'].strftime('%Y-%m')].append(t)
        for m in sorted(monthly):
            mt  = monthly[m]
            mw  = sum(1 for t in mt if t['result'] == 'win')
            meq = calc_equity(mt, RR, INITIAL_CAPITAL, RISK_PCT)
            bar = '▓' * max(0, int((mw/len(mt)*100 - 25) / 2))
            print(f"  {m}  {len(mt):>5}회  {mw/len(mt)*100:>5.1f}%  {meq['roi']:>+7.1f}%  {bar}")
        print(f"{'═'*80}")


# ═══════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════

if __name__ == '__main__':
    symbol  = 'BTC/USDT'
    limit   = 17520   # 1년
    fetcher = DataFetcher()
    ict     = ICTEngine()

    print(f"\n{'═'*80}")
    print(f"  📊 전략 비교 백테스트  |  {symbol}  |  1년  |  RR {RR}:1")
    print(f"  초기자본 {INITIAL_CAPITAL:.0f} USDT  |  고정 리스크 {RISK_PCT*100:.0f}%/거래")
    print(f"{'═'*80}")

    # ── 데이터 수집 ──
    print("\n📡 데이터 수집 중...")
    limit_4h = limit // 16 + 100
    limit_1d = limit // 96 + 50
    df_15m   = fetcher.fetch_ohlcv(symbol, '15m', limit=limit)
    df_4h    = fetcher.fetch_ohlcv(symbol, '4h',  limit=limit_4h)
    df_1d    = fetcher.fetch_ohlcv(symbol, '1d',  limit=limit_1d)

    if df_15m is None:
        print("❌ 데이터 수집 실패"); exit()

    # 지표 선계산
    df_15m = df_15m.copy()
    df_15m['body_size']   = abs(df_15m['close'] - df_15m['open'])
    df_15m['avg_body']    = df_15m['body_size'].rolling(10).mean()
    df_15m['swing_high']  = df_15m['high'].rolling(5, center=True).max()
    df_15m['swing_low']   = df_15m['low'].rolling(5, center=True).min()
    df_15m['roll_max_20'] = df_15m['high'].shift(1).rolling(20).max()
    df_15m['roll_min_20'] = df_15m['low'].shift(1).rolling(20).min()
    print(f"  ✅ 15m({len(df_15m)}봉)  4h({len(df_4h)}봉)  1d({len(df_1d)}봉)")

    # 4H 오더플로우 선계산
    print("  ⚙️  4H 오더플로우 상태 계산 중...")
    of_states = build_order_flow_states(df_4h, swing_window=5)

    # ── 각 전략 시뮬레이션 ──
    print("\n  시뮬레이션 실행 중...")

    results = []

    print("    A. 위성 전략 v3 ...", end='', flush=True)
    t_sat = simulate_satellite(df_15m, df_4h, df_1d, ict)
    results.append(strategy_stats(t_sat,  RR, 'A. 위성 v3 (1D+4H+킬존+스윕)'))
    print(f" {len(t_sat)}건")

    print("    B. 오더플로우 WITH ...", end='', flush=True)
    t_ofw = simulate_of_with(df_15m, df_4h, ict, of_states)
    results.append(strategy_stats(t_ofw, RR, 'B. 오더플로우 WITH'))
    print(f" {len(t_ofw)}건")

    print("    C. 스윕 반전 (필터 없음) ...", end='', flush=True)
    t_sw_all = simulate_sweep(df_15m, ict, kz_only=False)
    results.append(strategy_stats(t_sw_all, RR, 'C. 스윕반전 전체'))
    print(f" {len(t_sw_all)}건")

    print("    D. 스윕 반전 + 킬존 ...", end='', flush=True)
    t_sw_kz = simulate_sweep(df_15m, ict, kz_only=True)
    results.append(strategy_stats(t_sw_kz, RR, 'D. 스윕반전 + 킬존 ★'))
    print(f" {len(t_sw_kz)}건")

    # ── 비교 출력 ──
    print_comparison(results)
