"""
아이린 메인 v5 — 실데이터 OI/L/S 포지션 사이징 백테스터
────────────────────────────────────────────────
바이비트 API에서 실제 미결제약정(OI) + 롱숏 비율(L/S) 히스토리를 가져와
위성 v3 진입 조건 위에 가변 포지션 사이징을 적용한다.

외부 데이터 점수 → 리스크 배율:
  BUY  셋업: L/S short_heavy(+1.5) + OI rising(+1.0) 최대 2.5점
  SELL 셋업: L/S long_heavy(+1.5)  + OI rising(+1.0) 최대 2.5점

  score >= 2.0 → 3% 리스크
  score >= 1.0 → 2% 리스크
  score <  1.0 → 1% 리스크

비교:
  A. 위성 v3   — 고정 1%
  B. 메인 v5   — 가변 1~3% (실 OI/L/S 기반)
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
from datetime import datetime
from collections import defaultdict
from core.ict_engine import ICTEngine
from core.data_fetcher import DataFetcher
from strategy.sweep_reversal_backtester import find_sweep_reversal_setups, is_kill_zone


INITIAL_CAPITAL = 1000.0
FIXED_RR        = 3.0
LIMIT           = 17520   # 1년 15m 봉


# ══════════════════════════════════════════════
#  실 OI/L/S 히스토리 수집
# ══════════════════════════════════════════════

def fetch_real_external_data(fetcher, symbol='BTC/USDT'):
    """
    바이비트 API로 OI(1d 최대 200봉) + L/S(1d 최대 500봉) 수집.
    날짜 문자열('YYYY-MM-DD')을 키로 하는 룩업 테이블 반환.
    """
    bybit_symbol = symbol.replace('/', '').replace(':USDT', '')
    oi_lookup = {}   # date_str → 'rising'|'falling'|'neutral'
    ls_lookup = {}   # date_str → 'long_heavy'|'short_heavy'|'neutral'

    # ── OI 1d 히스토리 ──
    print("  OI 히스토리 수집 중...", end='', flush=True)
    try:
        params = {'category': 'linear', 'symbol': bybit_symbol,
                  'intervalTime': '1d', 'limit': 200}
        resp = fetcher.exchange.public_get_v5_market_open_interest(params)
        items_raw = resp.get('result', {}).get('list', [])
        if items_raw:
            items = list(reversed(items_raw))   # 오래된 순
            for j in range(1, len(items)):
                ts   = int(items[j]['timestamp']) / 1000
                date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                oi_now  = float(items[j]['openInterest'])
                oi_prev = float(items[j-1]['openInterest'])
                chg_pct = (oi_now - oi_prev) / oi_prev * 100 if oi_prev > 0 else 0
                oi_lookup[date] = ('rising' if chg_pct > 2.0
                                   else ('falling' if chg_pct < -2.0 else 'neutral'))
            start_oi = datetime.fromtimestamp(int(items[0]['timestamp'])/1000).strftime('%Y-%m-%d')
            end_oi   = datetime.fromtimestamp(int(items[-1]['timestamp'])/1000).strftime('%Y-%m-%d')
            print(f" {len(oi_lookup)}건 ({start_oi} ~ {end_oi})")
        else:
            print(f" 결과 없음 (retCode={resp.get('retCode')})")
    except Exception as e:
        print(f" 오류: {e}")
    time.sleep(0.3)

    # ── L/S 1d 히스토리 ──
    print("  L/S 히스토리 수집 중...", end='', flush=True)
    try:
        params2 = {'category': 'linear', 'symbol': bybit_symbol,
                   'period': '1d', 'limit': 500}
        resp2 = fetcher.exchange.public_get_v5_market_account_ratio(params2)
        items2 = resp2.get('result', {}).get('list', [])
        if items2:
            for item in items2:
                ts   = int(item['timestamp']) / 1000
                date = datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                buy  = float(item.get('buyRatio', 0.5))
                sell = float(item.get('sellRatio', 0.5))
                ratio = buy / sell if sell > 0 else 1.0
                ls_lookup[date] = ('long_heavy'  if ratio > 1.5
                                   else ('short_heavy' if ratio < 0.67 else 'neutral'))
            start_ls = datetime.fromtimestamp(int(items2[-1]['timestamp'])/1000).strftime('%Y-%m-%d')
            end_ls   = datetime.fromtimestamp(int(items2[0]['timestamp'])/1000).strftime('%Y-%m-%d')
            print(f" {len(ls_lookup)}건 ({start_ls} ~ {end_ls})")
        else:
            print(f" 결과 없음 (retCode={resp2.get('retCode')})")
    except Exception as e:
        print(f" 오류: {e}")

    return oi_lookup, ls_lookup


def real_ext_score(dt, oi_lookup, ls_lookup, side):
    """
    실 OI + L/S 데이터로 포지션 사이징 점수 계산 (0.0 ~ 2.5)

    BUY  셋업: short_heavy(많은 숏 = 스퀴즈 잠재력) + OI rising
    SELL 셋업: long_heavy (많은 롱 = 청산 잠재력) + OI rising
    """
    date_key = dt.strftime('%Y-%m-%d')
    oi_trend = oi_lookup.get(date_key, 'neutral')
    ls_bias  = ls_lookup.get(date_key, 'neutral')

    score = 0.0

    # OI 점수
    if oi_trend == 'rising':   score += 1.0
    elif oi_trend == 'neutral': score += 0.3

    # L/S 역발상 점수
    if side == 'buy':
        if ls_bias == 'short_heavy': score += 1.5
        elif ls_bias == 'neutral':   score += 0.5
    else:  # sell
        if ls_bias == 'long_heavy':  score += 1.5
        elif ls_bias == 'neutral':   score += 0.5

    return round(score, 2)


def score_to_risk(score):
    if score >= 2.0: return 0.030
    if score >= 1.0: return 0.020
    return            0.010


# ══════════════════════════════════════════════
#  OHLCV 수집
# ══════════════════════════════════════════════

def fetch_ohlcv_all(fetcher):
    print("  OHLCV 수집 중...", end='', flush=True)
    df_15m = fetcher.fetch_ohlcv('BTC/USDT', '15m', limit=LIMIT)
    df_4h  = fetcher.fetch_ohlcv('BTC/USDT', '4h',  limit=LIMIT//16+100)
    df_1d  = fetcher.fetch_ohlcv('BTC/USDT', '1d',  limit=LIMIT//96+50)
    if df_15m is None:
        print(" 실패"); return None

    df_15m = df_15m.copy()
    for col, w in [('body_size', None), ('avg_body', 10), ('swing_high', None),
                    ('swing_low', None), ('roll_max_20', None), ('roll_min_20', None)]:
        if col == 'body_size':
            df_15m[col] = abs(df_15m['close'] - df_15m['open'])
        elif col == 'avg_body':
            df_15m[col] = df_15m['body_size'].rolling(w).mean()
        elif col == 'swing_high':
            df_15m[col] = df_15m['high'].rolling(5, center=True).max()
        elif col == 'swing_low':
            df_15m[col] = df_15m['low'].rolling(5, center=True).min()
        elif col == 'roll_max_20':
            df_15m[col] = df_15m['high'].shift(1).rolling(20).max()
        elif col == 'roll_min_20':
            df_15m[col] = df_15m['low'].shift(1).rolling(20).min()

    print(f" 15m({len(df_15m)}) 4h({len(df_4h)}) 1d({len(df_1d)})")
    return df_15m, df_4h, df_1d


# ══════════════════════════════════════════════
#  거래 헬퍼
# ══════════════════════════════════════════════

def check_trade(trade, row):
    if trade is None: return None
    side   = trade['side']
    sl, tp = trade['sl'], trade['tp']
    result = None
    if side == 'buy':
        if row['low']  <= sl: result = 'loss'
        elif row['high'] >= tp: result = 'win'
    else:
        if row['high'] >= sl: result = 'loss'
        elif row['low']  <= tp: result = 'win'
    if result is None:
        h = (row['timestamp'] - trade['entry_time']).total_seconds() / 3600
        if h >= 24: result = 'timeout'
    if result:
        trade['result'] = result
        return trade
    return None


def make_trade(side, zone, price, ct, risk_pct, capital, extra=None):
    if side == 'buy':
        sl = zone['bottom'] * 0.999
        tp = price + (price - sl) * FIXED_RR
    else:
        sl = zone['top'] * 1.001
        tp = price - (sl - price) * FIXED_RR
    sl_pct = abs(price - sl) / price * 100
    if not (0.15 <= sl_pct <= 3.0): return None
    risk_amt = capital * risk_pct
    qty = risk_amt / abs(price - sl)
    t = {'side': side, 'entry_price': price, 'sl': sl, 'tp': tp,
         'entry_time': ct, 'risk_pct': risk_pct, 'qty': qty, 'result': None}
    if extra: t.update(extra)
    return t


# ══════════════════════════════════════════════
#  공통 진입 루프 (위성 v3 조건)
# ══════════════════════════════════════════════

def _run_loop(df_15m, df_4h, df_1d, ict_engine, risk_fn):
    """
    위성 v3 진입 조건으로 루프 실행.
    risk_fn(side, ct, price) → risk_pct
    """
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

        done = check_trade(current_trade, row)
        if done:
            risk_amt = done['qty'] * abs(done['entry_price'] - done['sl'])
            pnl = risk_amt * FIXED_RR if done['result'] == 'win' else \
                  (-risk_amt if done['result'] == 'loss' else 0)
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
            risk_pct = risk_fn(side, ct, price_now)
            t = make_trade(side, z, price_now, ct, risk_pct, capital)
            if t:
                current_trade = t
                break

    return trades, equity


# ══════════════════════════════════════════════
#  전략 실행
# ══════════════════════════════════════════════

def simulate_satellite_v3(df_15m, df_4h, df_1d, ict):
    print("  [A. 위성 v3]   시뮬레이션 중...", end='', flush=True)
    trades, equity = _run_loop(df_15m, df_4h, df_1d, ict,
                               risk_fn=lambda side, ct, price: 0.01)
    print(f" {len(trades)}건 완료")
    return trades, equity


def simulate_main_v5(df_15m, df_4h, df_1d, ict, oi_lookup, ls_lookup):
    print("  [B. 메인 v5]   시뮬레이션 중...", end='', flush=True)

    def risk_fn(side, ct, price):
        score = real_ext_score(ct, oi_lookup, ls_lookup, side)
        r = score_to_risk(score)
        return r

    trades, equity = _run_loop(df_15m, df_4h, df_1d, ict, risk_fn=risk_fn)

    # ext_score 역추적하여 trades에 추가
    for t in trades:
        t['ext_score'] = real_ext_score(t['entry_time'], oi_lookup, ls_lookup, t['side'])

    print(f" {len(trades)}건 완료")
    return trades, equity


# ══════════════════════════════════════════════
#  결과 출력
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


def print_results(results, oi_lookup, ls_lookup):
    print(f"\n{'═'*80}")
    print(f"  {'전략':<32} {'거래':>5}  {'승률':>6}  {'ROI':>8}  {'MDD':>6}  {'최종자본':>10}")
    print(f"  {'─'*78}")
    best_roi = max(r['roi'] for r in results)
    for r in results:
        marker = ' ◀ 최고' if r['roi'] == best_roi else ''
        print(f"  {r['label']:<32} {r['n']:>5}회  {r['wr']:>5.1f}%  "
              f"{r['roi']:>+7.1f}%  {r['mdd']:>5.1f}%  "
              f"{r['final']:>9,.0f}U{marker}")
    print(f"{'═'*80}")

    # 메인 v5 리스크 분포
    for r in results:
        if 'v5' in r['label'] and r['trades']:
            scores  = [t.get('ext_score', 0) for t in r['trades']]
            r1 = sum(1 for s in scores if s < 1.0)
            r2 = sum(1 for s in scores if 1.0 <= s < 2.0)
            r3 = sum(1 for s in scores if s >= 2.0)
            wins_r1 = sum(1 for t in r['trades'] if t.get('ext_score',0) < 1.0 and t['result']=='win')
            wins_r2 = sum(1 for t in r['trades'] if 1.0 <= t.get('ext_score',0) < 2.0 and t['result']=='win')
            wins_r3 = sum(1 for t in r['trades'] if t.get('ext_score',0) >= 2.0 and t['result']=='win')
            print(f"\n  [메인 v5] 리스크 구간별 성과 (실 OI/L/S 기반):")
            print(f"    1% (score <1.0) : {r1:>3}건  승률 {wins_r1/r1*100:.0f}%" if r1 else f"    1% (score <1.0) :   0건")
            print(f"    2% (1.0≤score<2): {r2:>3}건  승률 {wins_r2/r2*100:.0f}%" if r2 else f"    2% (1.0≤score<2):   0건")
            print(f"    3% (score ≥2.0) : {r3:>3}건  승률 {wins_r3/r3*100:.0f}%" if r3 else f"    3% (score ≥2.0) :   0건")

    # OI/L/S 커버리지 통계
    oi_days  = len(oi_lookup)
    ls_days  = len(ls_lookup)
    oi_rise  = sum(1 for v in oi_lookup.values() if v == 'rising')
    ls_lh    = sum(1 for v in ls_lookup.values() if v == 'long_heavy')
    ls_sh    = sum(1 for v in ls_lookup.values() if v == 'short_heavy')
    print(f"\n  [실 데이터 요약]")
    print(f"    OI 데이터: {oi_days}일  (상승 {oi_rise}일 / {oi_rise/oi_days*100:.0f}%)")
    print(f"    L/S 데이터: {ls_days}일 (롱과밀 {ls_lh}일 / 숏과밀 {ls_sh}일)")

    # 월별 상세
    print(f"\n  {'월':>8}  {'위성v3':>8}  {'승률':>6}  {'메인v5':>8}  {'승률':>6}  {'평균점수':>8}  {'OI추세':>8}")
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
            row_parts.append(f"{len(mt):>6}회  {wr_m:>5.1f}%")

            if 'v5' in r['label'] and mt:
                avg_s  = sum(t.get('ext_score', 0) for t in mt) / len(mt)
                # 해당 월 OI 평균 추세
                oi_vals = [oi_lookup.get(f"{m}-{str(d).zfill(2)}", 'neutral') for d in range(1, 32)]
                oi_rise_cnt = oi_vals.count('rising')
                oi_total    = sum(1 for v in oi_vals if v != 'neutral')
                oi_tag = f"↑{oi_rise_cnt/oi_total*100:.0f}%" if oi_total else '  n/a'
                row_parts.append(f"{avg_s:>6.1f}점  {oi_tag:>8}")

        print("  ".join(row_parts))

    print(f"{'═'*80}")


# ══════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════

if __name__ == '__main__':
    print(f"\n{'═'*80}")
    print(f"  메인 v5 실데이터 검증  |  BTC/USDT  |  1년  |  RR 3:1")
    print(f"  위성 v3: 고정 1%  |  메인 v5: 실 OI/L/S 기반 가변 1~3%")
    print(f"{'═'*80}\n")

    fetcher = DataFetcher()

    print("📡 실 외부 데이터 수집 중...")
    oi_lookup, ls_lookup = fetch_real_external_data(fetcher)

    print("\n📡 OHLCV 데이터 수집 중...")
    data = fetch_ohlcv_all(fetcher)
    if not data: exit()
    df_15m, df_4h, df_1d = data

    ict = ICTEngine()

    print()
    t_sat,  eq_sat  = simulate_satellite_v3(df_15m, df_4h, df_1d, ict)
    t_main, eq_main = simulate_main_v5(df_15m, df_4h, df_1d, ict, oi_lookup, ls_lookup)

    results = [
        calc_stats(t_sat,  eq_sat,  'A. 위성 v3  (고정 1%)'),
        calc_stats(t_main, eq_main, 'B. 메인 v5  (실 OI/L/S)'),
    ]

    print_results(results, oi_lookup, ls_lookup)
