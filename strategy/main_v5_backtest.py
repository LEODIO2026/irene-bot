"""
아이린 메인 전략 v5 백테스터
────────────────────────────────────────────────
v5 설계 원칙:
  진입 = 위성 v3와 동일 (1D BOS/MSS + 200EMA + 4H EMA + 킬존 + 스윕+FVG)
  포지션 사이징 = 외부 데이터 점수 기반 가변 리스크

  외부 데이터 점수 → 리스크 배율:
    0.0 ~ 0.9  : 기본 1.0% (확신 부족)
    1.0 ~ 1.9  : 2.0%      (단일 확인)
    2.0+       : 3.0%      (복수 확인 = 최고 확신)

비교 대상:
  A. 위성 v3       — 고정 1% 리스크, 1년 226회
  B. 메인 v5       — 가변 1~3% 리스크, 동일 셋업
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from collections import defaultdict
from core.ict_engine import ICTEngine
from core.data_fetcher import DataFetcher
from strategy.sweep_reversal_backtester import find_sweep_reversal_setups, is_kill_zone


INITIAL_CAPITAL = 1000.0
FIXED_RR        = 3.0
LIMIT           = 17520   # 1년


# ══════════════════════════════════════════════
#  데이터 수집
# ══════════════════════════════════════════════

def fetch_all(fetcher):
    print("📡 데이터 수집 중...")
    df_15m = fetcher.fetch_ohlcv('BTC/USDT', '15m', limit=LIMIT)
    df_4h  = fetcher.fetch_ohlcv('BTC/USDT', '4h',  limit=LIMIT//16+100)
    df_1d  = fetcher.fetch_ohlcv('BTC/USDT', '1d',  limit=LIMIT//96+50)

    if df_15m is None:
        print("❌ 데이터 수집 실패"); return None

    df_15m = df_15m.copy()
    df_15m['body_size']   = abs(df_15m['close'] - df_15m['open'])
    df_15m['avg_body']    = df_15m['body_size'].rolling(10).mean()
    df_15m['swing_high']  = df_15m['high'].rolling(5, center=True).max()
    df_15m['swing_low']   = df_15m['low'].rolling(5, center=True).min()
    df_15m['roll_max_20'] = df_15m['high'].shift(1).rolling(20).max()
    df_15m['roll_min_20'] = df_15m['low'].shift(1).rolling(20).min()

    print(f"  ✅ 15m({len(df_15m)})  4h({len(df_4h)})  1d({len(df_1d)})")
    return df_15m, df_4h, df_1d


# ══════════════════════════════════════════════
#  외부 데이터 점수 시뮬 (RSI + 볼륨 기반)
# ══════════════════════════════════════════════

def ext_score(df_snap, side):
    """
    RSI + 볼륨 패턴으로 외부 데이터 점수 근사 (0.0 ~ 3.0)
    - 군중심리 역발상: RSI 극단 + 방향 반대 쏠림 → +1.0
    - 세력 감지: 고볼륨 + OI 상승 시뮬 → +1.0
    - 스마트머니: 큰 바디 + 고볼륨 → +1.0
    """
    close  = df_snap['close']
    volume = df_snap['volume']
    last   = df_snap.iloc[-1]

    # RSI 14
    delta = close.diff()
    gain  = delta.clip(lower=0).tail(15).mean()
    loss  = (-delta.clip(upper=0)).tail(15).mean()
    rsi   = 100 - (100 / (1 + gain/loss)) if loss > 0 else 50.0

    # 볼륨 비율
    vol_avg   = volume.tail(20).mean()
    vol_ratio = last['volume'] / vol_avg if vol_avg > 0 else 1.0

    # 가격 모멘텀
    ref     = close.iloc[-11] if len(close) >= 11 else close.iloc[0]
    mom_pct = (last['close'] - ref) / ref * 100

    # 볼륨 기울기 → OI 시뮬
    vol_s   = volume.tail(6)
    v_slope = (vol_s.iloc[-1] - vol_s.iloc[0]) / (vol_s.iloc[0] + 1)
    oi_pct  = v_slope * 3 + mom_pct * 0.4
    oi_up   = oi_pct > 1.5

    score = 0.0

    # ① 군중심리 역발상
    if side == 'buy':
        if rsi < 35:   score += 1.0   # 숏 극단 과밀 → 반등 기대
        elif rsi < 45: score += 0.5
    else:
        if rsi > 65:   score += 1.0   # 롱 극단 과밀 → 하락 기대
        elif rsi > 55: score += 0.5

    # ② 세력 감지 (OI 상승 + 볼륨 급증)
    if oi_up and vol_ratio > 1.5:
        score += 1.0
    elif oi_up or vol_ratio > 1.5:
        score += 0.5

    # ③ 스마트머니 (큰 바디 + 고볼륨)
    body_size = abs(last['close'] - last['open'])
    avg_body  = close.diff().abs().tail(10).mean()
    if body_size > avg_body * 1.5 and vol_ratio > 1.5 and oi_up:
        score += 1.0
    elif vol_ratio > 1.5 and oi_up:
        score += 0.5

    return round(score, 2)


def score_to_risk(score):
    """외부 점수 → 리스크 비율"""
    if score >= 2.0: return 0.030   # 3%
    if score >= 1.0: return 0.020   # 2%
    return            0.010          # 1%


# ══════════════════════════════════════════════
#  공통: 거래 체크 + 생성
# ══════════════════════════════════════════════

def check_trade(current_trade, row, rr):
    if current_trade is None: return None
    side   = current_trade['side']
    sl, tp = current_trade['sl'], current_trade['tp']
    result = None

    if side == 'buy':
        if row['low']  <= sl: result = 'loss'
        elif row['high'] >= tp: result = 'win'
    else:
        if row['high'] >= sl: result = 'loss'
        elif row['low']  <= tp: result = 'win'

    if result is None:
        h = (row['timestamp'] - current_trade['entry_time']).total_seconds() / 3600
        if h >= 24: result = 'timeout'

    if result:
        current_trade['result'] = result
        return current_trade
    return None


def make_trade(side, zone, price, current_time, rr, risk_pct, capital):
    if side == 'buy':
        sl = zone['bottom'] * 0.999
        tp = price + (price - sl) * rr
    else:
        sl = zone['top'] * 1.001
        tp = price - (sl - price) * rr

    sl_pct = abs(price - sl) / price * 100
    if not (0.15 <= sl_pct <= 3.0):
        return None

    risk_amt = capital * risk_pct
    qty = risk_amt / (abs(price - sl))

    return {
        'side': side, 'entry_price': price,
        'sl': sl, 'tp': tp,
        'entry_time': current_time,
        'risk_pct': risk_pct,
        'qty': qty,
        'result': None,
    }


# ══════════════════════════════════════════════
#  A. 위성 v3 시뮬 (고정 1% 리스크)
# ══════════════════════════════════════════════

def simulate_satellite_v3(df_15m, df_4h, df_1d, ict_engine):
    print("  [A. 위성 v3] 시뮬레이션 중...", end='', flush=True)
    trades = []
    current_trade = None
    capital = INITIAL_CAPITAL
    equity  = [capital]
    h4_idx = d1_idx = 0

    for i in range(200, len(df_15m)):
        row = df_15m.iloc[i]
        ct  = row['timestamp']

        while h4_idx + 1 < len(df_4h) and df_4h.iloc[h4_idx+1]['timestamp'] <= ct: h4_idx += 1
        while d1_idx + 1 < len(df_1d) and df_1d.iloc[d1_idx+1]['timestamp'] <= ct: d1_idx += 1

        done = check_trade(current_trade, row, FIXED_RR)
        if done:
            risk_amt = done['qty'] * abs(done['entry_price'] - done['sl'])
            pnl = risk_amt * FIXED_RR if done['result'] == 'win' else (-risk_amt if done['result'] == 'loss' else 0)
            capital += pnl
            equity.append(round(capital, 2))
            done['pnl'] = round(pnl, 2)
            trades.append(done)
            current_trade = None
            continue
        if current_trade: continue

        kz = is_kill_zone(ct)
        if not kz or kz == 'newyork_lunch': continue

        snap_1d = df_1d.iloc[max(0, d1_idx-49): d1_idx+1]
        if len(snap_1d) < 20: continue
        bos = ict_engine.detect_bos_mss(snap_1d, swing_window=3)
        struct_1d = bos['direction']
        if struct_1d == 'neutral': continue

        ema200 = snap_1d['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        price_now = float(row['close'])
        if price_now < ema200 and struct_1d == 'bullish': continue

        snap_4h = df_4h.iloc[max(0, h4_idx-49): h4_idx+1]
        if len(snap_4h) < 20: continue
        ema20_4h = snap_4h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        mom_4h = 'bullish' if float(snap_4h['close'].iloc[-1]) > ema20_4h else 'bearish'
        if mom_4h != struct_1d: continue

        side = 'buy' if struct_1d == 'bullish' else 'sell'
        snap_15m = df_15m.iloc[max(0, i-100): i+1]
        setups = find_sweep_reversal_setups(snap_15m, ict_engine)
        for z in setups:
            if z['side'] != side: continue
            if not (z['bottom'] * 0.999 <= price_now <= z['top'] * 1.001): continue
            t = make_trade(side, z, price_now, ct, FIXED_RR, 0.01, capital)
            if t:
                current_trade = t
                break

    print(f" {len(trades)}건 완료")
    return trades, equity


# ══════════════════════════════════════════════
#  B. 메인 v5 시뮬 (가변 1~3% 리스크)
# ══════════════════════════════════════════════

def simulate_main_v5(df_15m, df_4h, df_1d, ict_engine):
    print("  [B. 메인 v5] 시뮬레이션 중...", end='', flush=True)
    trades = []
    current_trade = None
    capital = INITIAL_CAPITAL
    equity  = [capital]
    h4_idx = d1_idx = 0

    for i in range(200, len(df_15m)):
        row = df_15m.iloc[i]
        ct  = row['timestamp']

        while h4_idx + 1 < len(df_4h) and df_4h.iloc[h4_idx+1]['timestamp'] <= ct: h4_idx += 1
        while d1_idx + 1 < len(df_1d) and df_1d.iloc[d1_idx+1]['timestamp'] <= ct: d1_idx += 1

        done = check_trade(current_trade, row, FIXED_RR)
        if done:
            risk_amt = done['qty'] * abs(done['entry_price'] - done['sl'])
            pnl = risk_amt * FIXED_RR if done['result'] == 'win' else (-risk_amt if done['result'] == 'loss' else 0)
            capital += pnl
            equity.append(round(capital, 2))
            done['pnl'] = round(pnl, 2)
            trades.append(done)
            current_trade = None
            continue
        if current_trade: continue

        kz = is_kill_zone(ct)
        if not kz or kz == 'newyork_lunch': continue

        snap_1d = df_1d.iloc[max(0, d1_idx-49): d1_idx+1]
        if len(snap_1d) < 20: continue
        bos = ict_engine.detect_bos_mss(snap_1d, swing_window=3)
        struct_1d = bos['direction']
        if struct_1d == 'neutral': continue

        ema200 = snap_1d['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        price_now = float(row['close'])
        if price_now < ema200 and struct_1d == 'bullish': continue

        snap_4h = df_4h.iloc[max(0, h4_idx-49): h4_idx+1]
        if len(snap_4h) < 20: continue
        ema20_4h = snap_4h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        mom_4h = 'bullish' if float(snap_4h['close'].iloc[-1]) > ema20_4h else 'bearish'
        if mom_4h != struct_1d: continue

        side = 'buy' if struct_1d == 'bullish' else 'sell'
        snap_15m = df_15m.iloc[max(0, i-100): i+1]
        setups = find_sweep_reversal_setups(snap_15m, ict_engine)

        for z in setups:
            if z['side'] != side: continue
            if not (z['bottom'] * 0.999 <= price_now <= z['top'] * 1.001): continue

            # ── 외부 데이터 점수 → 리스크 결정 ──
            score    = ext_score(snap_15m, side)
            risk_pct = score_to_risk(score)

            t = make_trade(side, z, price_now, ct, FIXED_RR, risk_pct, capital)
            if t:
                t['ext_score'] = score
                current_trade = t
                break

    print(f" {len(trades)}건 완료")
    return trades, equity


# ══════════════════════════════════════════════
#  결과 분석
# ══════════════════════════════════════════════

def calc_stats(trades, equity, label):
    if not trades:
        return {'label': label, 'n': 0, 'wr': 0, 'roi': 0, 'mdd': 0,
                'final': INITIAL_CAPITAL, 'trades': [], 'equity': [INITIAL_CAPITAL]}
    n    = len(trades)
    wins = sum(1 for t in trades if t['result'] == 'win')
    wr   = wins / n * 100

    peak, mdd = INITIAL_CAPITAL, 0.0
    for v in equity:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > mdd: mdd = dd

    final = equity[-1]
    roi   = (final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    return {'label': label, 'n': n, 'wr': wr, 'roi': roi, 'mdd': mdd,
            'final': final, 'trades': trades, 'equity': equity}


def print_results(results):
    print(f"\n{'═'*80}")
    print(f"  {'전략':<30} {'거래':>5}  {'승률':>6}  {'ROI':>8}  {'MDD':>6}  {'최종자본':>10}")
    print(f"  {'─'*78}")

    best_roi = max(r['roi'] for r in results)
    for r in results:
        marker = ' ◀ 최고' if r['roi'] == best_roi else ''
        print(f"  {r['label']:<30} {r['n']:>5}회  {r['wr']:>5.1f}%  "
              f"{r['roi']:>+7.1f}%  {r['mdd']:>5.1f}%  "
              f"{r['final']:>9,.0f}U{marker}")
    print(f"{'═'*80}")

    # 메인 v5 리스크 분포
    for r in results:
        if 'v5' in r['label'] and r['trades']:
            scores = [t.get('ext_score', 0) for t in r['trades']]
            r1 = sum(1 for s in scores if s < 1.0)
            r2 = sum(1 for s in scores if 1.0 <= s < 2.0)
            r3 = sum(1 for s in scores if s >= 2.0)
            print(f"\n  [메인 v5] 리스크 배분:")
            print(f"    1% 리스크 (외부 약) : {r1}건 ({r1/len(scores)*100:.0f}%)")
            print(f"    2% 리스크 (단일 확인): {r2}건 ({r2/len(scores)*100:.0f}%)")
            print(f"    3% 리스크 (복수 확인): {r3}건 ({r3/len(scores)*100:.0f}%)")

    # 월별 비교
    print(f"\n  {'월':>8}  {'위성v3 거래':>10}  {'승률':>6}  {'메인v5 거래':>10}  {'승률':>6}  {'평균리스크':>8}")
    monthly = {r['label']: defaultdict(list) for r in results}
    for r in results:
        for t in r['trades']:
            monthly[r['label']][t['entry_time'].strftime('%Y-%m')].append(t)

    all_months = sorted(set(m for r in results for m in monthly[r['label']]))
    for m in all_months:
        row_parts = [f"  {m}"]
        for r in results:
            mt  = monthly[r['label']].get(m, [])
            mw  = sum(1 for t in mt if t['result'] == 'win')
            wr_m = mw / len(mt) * 100 if mt else 0
            extra = ''
            if 'v5' in r['label'] and mt:
                avg_r = sum(t.get('ext_score', 0) for t in mt) / len(mt)
                extra = f"  {avg_r:.1f}점"
            row_parts.append(f"{len(mt):>8}회  {wr_m:>5.1f}%{extra}")
        print("  ".join(row_parts))

    print(f"{'═'*80}")


# ══════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════

if __name__ == '__main__':
    print(f"\n{'═'*80}")
    print(f"  메인 v5 vs 위성 v3  |  BTC/USDT  |  1년  |  RR 3:1")
    print(f"  초기자본 {INITIAL_CAPITAL:.0f} USDT")
    print(f"  위성: 고정 1% / 메인 v5: 가변 1~3% (외부 데이터 기반)")
    print(f"{'═'*80}")

    fetcher = DataFetcher()
    data    = fetch_all(fetcher)
    if not data: exit()
    df_15m, df_4h, df_1d = data

    ict = ICTEngine()

    print()
    t_sat,  eq_sat  = simulate_satellite_v3(df_15m, df_4h, df_1d, ict)
    t_main, eq_main = simulate_main_v5(df_15m, df_4h, df_1d, ict)

    results = [
        calc_stats(t_sat,  eq_sat,  'A. 위성 v3  (고정 1%)'),
        calc_stats(t_main, eq_main, 'B. 메인 v5  (가변 1~3%)'),
    ]

    print_results(results)
