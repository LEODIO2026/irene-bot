"""
컨플루언스 임계값 비교 백테스터
────────────────────────────────────────────────
메인 전략을 두 가지 임계값으로 비교:

  A. 기존: min_confluence 4.7  (보수적)
  B. 완화: min_confluence 4.0  (현실적)

공통 조건:
  - 심볼: BTC/USDT
  - 기간: 1년 (15m 17520봉)
  - 초기 자본 1000 USDT
  - 리스크 2.5%/거래 (메인 전략 기본값)
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import timedelta
from collections import defaultdict
from core.ict_engine import ICTEngine
from core.decision_maker import DecisionMaker
from core.data_fetcher import DataFetcher
from execution.risk_manager import RiskManager


INITIAL_CAPITAL = 1000.0
RISK_PCT        = 0.025
LIMIT           = 17520   # 1년


# ══════════════════════════════════════════════
#  데이터 수집 (공용)
# ══════════════════════════════════════════════

def fetch_data(fetcher, limit=LIMIT):
    print("📡 데이터 수집 중...")
    limit_4h = limit // 16 + 100
    limit_1d = limit // 96 + 50

    df_15m = fetcher.fetch_ohlcv('BTC/USDT', '15m', limit=limit)
    df_4h  = fetcher.fetch_ohlcv('BTC/USDT', '4h',  limit=limit_4h)
    df_1d  = fetcher.fetch_ohlcv('BTC/USDT', '1d',  limit=limit_1d)

    if df_15m is None:
        print("❌ 데이터 수집 실패"); return None

    # 지표 선계산
    df_15m = df_15m.copy()
    df_15m['swing_high']  = df_15m['high'].rolling(5, center=True).max()
    df_15m['swing_low']   = df_15m['low'].rolling(5, center=True).min()
    df_15m['body_size']   = abs(df_15m['close'] - df_15m['open'])
    df_15m['avg_body']    = df_15m['body_size'].rolling(10).mean()
    df_15m['roll_max_20'] = df_15m['high'].shift(1).rolling(20).max()
    df_15m['roll_min_20'] = df_15m['low'].shift(1).rolling(20).min()

    if df_4h is not None:
        df_4h = df_4h.copy()
        df_4h['ema50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
    if df_1d is not None:
        df_1d = df_1d.copy()
        df_1d['ema50'] = df_1d['close'].ewm(span=50, adjust=False).mean()

    print(f"  ✅ 15m({len(df_15m)})  4h({len(df_4h)})  1d({len(df_1d)})")
    return df_15m, df_4h, df_1d


# ══════════════════════════════════════════════
#  외부 데이터 시뮬 (backtester.py와 동일)
# ══════════════════════════════════════════════

def simulate_external_data(df_snapshot, htf_bias):
    last_row  = df_snapshot.iloc[-1]
    close     = df_snapshot['close']
    volume    = df_snapshot['volume']
    vol_avg   = volume.tail(20).mean()
    vol_ratio = last_row['volume'] / vol_avg if vol_avg > 0 else 1.0

    delta = close.diff()
    gain  = delta.clip(lower=0).tail(15).mean()
    loss  = (-delta.clip(upper=0)).tail(15).mean()
    rsi   = 100 - (100 / (1 + gain / loss)) if loss > 0 else 50.0

    price_ref    = close.iloc[-11] if len(close) >= 11 else close.iloc[0]
    momentum_pct = (last_row['close'] - price_ref) / price_ref * 100

    vol_series      = volume.tail(6)
    vol_slope       = (vol_series.iloc[-1] - vol_series.iloc[0]) / (vol_series.iloc[0] + 1)
    mock_oi_chg_pct = round(vol_slope * 3 + momentum_pct * 0.4, 2)
    oi_trend = 'rising' if mock_oi_chg_pct > 1.5 else ('falling' if mock_oi_chg_pct < -1.5 else 'neutral')

    if rsi > 65:    ls_ratio, ls_bias = 1.85, 'long_heavy'
    elif rsi < 35:  ls_ratio, ls_bias = 0.52, 'short_heavy'
    elif htf_bias == 'bearish': ls_ratio, ls_bias = 1.45, 'long_heavy'
    else:           ls_ratio, ls_bias = 0.72, 'short_heavy'

    oi_score  = 0.35 if oi_trend == 'rising' else (0.1 if oi_trend == 'neutral' else 0)
    ls_score  = 0.15 if (htf_bias == 'bearish' and ls_bias == 'long_heavy') or \
                        (htf_bias == 'bullish' and ls_bias == 'short_heavy') else 0
    whale_mock = {'score': round(min(1.0, oi_score + ls_score), 2),
                  'reasons': [], 'oi_info': {}}

    body_size = abs(last_row['close'] - last_row['open'])
    avg_body  = close.diff().abs().tail(10).mean()
    big_body  = body_size > avg_body * 1.5
    high_vol  = vol_ratio > 1.5
    sm_score  = 0.0
    sm_intent = 'watching'
    if big_body and high_vol and oi_trend == 'rising':  sm_score, sm_intent = 0.8, 'absorption'
    elif high_vol and oi_trend == 'rising':             sm_score, sm_intent = 0.5, 'accumulation'
    elif high_vol or oi_trend == 'rising':              sm_score, sm_intent = 0.3, 'accumulation'
    sm_mock = {'score': sm_score, 'intent': sm_intent, 'change_pct': mock_oi_chg_pct,
               'reasons': [f"💎 세력 {sm_intent} (가상)"] if sm_score > 0 else []}

    crowd_score, crowd_reasons = 0.0, []
    if htf_bias == 'bullish':
        if ls_bias == 'short_heavy' and rsi < 45:  crowd_score = 0.7; crowd_reasons.append("🧠 숏 과밀+RSI 저점 (가상)")
        elif ls_bias == 'short_heavy':              crowd_score = 0.4; crowd_reasons.append("🧠 숏 과밀 (가상)")
    else:
        if ls_bias == 'long_heavy' and rsi > 55:   crowd_score = 0.7; crowd_reasons.append("🧠 롱 과밀+RSI 고점 (가상)")
        elif ls_bias == 'long_heavy':               crowd_score = 0.4; crowd_reasons.append("🧠 롱 과밀 (가상)")
    crowd_mock = {'score': crowd_score, 'reasons': crowd_reasons,
                  'details': {'ls_ratio': ls_ratio, 'rsi': round(rsi,1), 'ls_bias': ls_bias, 'fear_greed': int(rsi)}}

    price_20_ref = close.iloc[-21] if len(close) >= 21 else close.iloc[0]
    trend_20_pct = (last_row['close'] - price_20_ref) / price_20_ref * 100
    news_score   = 0.0; news_reasons = []
    if htf_bias == 'bullish' and trend_20_pct > 2.5:
        news_score = min(0.5, trend_20_pct * 0.08); news_reasons.append(f"📰 상승 추세 (가상)")
    elif htf_bias == 'bearish' and trend_20_pct < -2.5:
        news_score = min(0.5, abs(trend_20_pct) * 0.08); news_reasons.append(f"📰 하락 추세 (가상)")
    news_mock = {'score': round(news_score,2), 'reasons': news_reasons, 'details': {}}

    return {'smart_money': sm_mock, 'crowd': crowd_mock, 'whale': whale_mock,
            'news': news_mock}


def calc_rsi(close_series, period=14):
    delta = close_series.diff()
    gain  = delta.clip(lower=0).tail(period+1).mean()
    loss  = (-delta.clip(upper=0)).tail(period+1).mean()
    return 100 - (100 / (1 + gain/loss)) if loss > 0 else 50.0


def check_4h_momentum(df_4h, action):
    if len(df_4h) < 20: return True
    ema20 = df_4h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
    cur   = df_4h['close'].iloc[-1]
    return cur > ema20 if action == 'buy' else cur < ema20


# ══════════════════════════════════════════════
#  메인 전략 시뮬레이터
# ══════════════════════════════════════════════

def run_main_strategy(df_15m, df_4h_full, df_1d_full, min_confluence, label, use_external=True):
    print(f"\n  [{label}] min_confluence={min_confluence} 시뮬레이션 중...", end='', flush=True)

    ict_engine = ICTEngine()
    dm = DecisionMaker(
        ict_engine,
        min_confluence=min_confluence,
        enable_ltf_scalp=True,
        ltf_scalp_min_confluence=3.5,
        scalp_cooldown_minutes=90,
    )
    risk_mgr    = RiskManager(risk_per_trade=RISK_PCT)
    capital     = INITIAL_CAPITAL
    equity      = [capital]
    trades      = []
    current_trade = None
    consec_loss   = 0
    cooldown_until = None

    h4_idx = d1_idx = 0

    for i in range(100, len(df_15m)):
        row  = df_15m.iloc[i]
        ct   = row['timestamp']

        while h4_idx + 1 < len(df_4h_full) and df_4h_full.iloc[h4_idx+1]['timestamp'] <= ct:
            h4_idx += 1
        while d1_idx + 1 < len(df_1d_full) and df_1d_full.iloc[d1_idx+1]['timestamp'] <= ct:
            d1_idx += 1

        # ── 열린 포지션 체크 ──
        if current_trade is not None:
            side = current_trade['side']
            sl, tp = current_trade['sl'], current_trade['tp']
            exit_price = exit_type = None

            if side == 'buy':
                if row['low']  <= sl: exit_price, exit_type = sl, 'loss'
                elif row['high'] >= tp: exit_price, exit_type = tp, 'profit'
            else:
                if row['high'] >= sl: exit_price, exit_type = sl, 'loss'
                elif row['low']  <= tp: exit_price, exit_type = tp, 'profit'

            if exit_price is None:
                hrs = (ct - current_trade['entry_time']).total_seconds() / 3600
                if hrs >= 48:
                    exit_price, exit_type = row['close'], 'time_stop'

            if exit_price:
                qty = current_trade['qty']
                ep  = current_trade['entry_price']
                pnl = (exit_price-ep)*qty if side=='buy' else (ep-exit_price)*qty
                fee = (ep + exit_price) * qty * 0.0006
                net = pnl - fee
                capital += net
                equity.append(round(capital, 2))
                current_trade.update({'exit_price': exit_price, 'exit_time': ct,
                                      'pnl': round(net,2), 'result': exit_type})
                trades.append(current_trade)

                if current_trade.get('scalp_mode'):
                    dm.record_scalp_trade(current_time=ct)
                else:
                    dm.record_trade(current_time=ct)

                if exit_type in ('loss', 'time_stop'):
                    consec_loss += 1
                    if consec_loss >= 7:    cooldown_until = ct + timedelta(hours=48)
                    elif consec_loss >= 5:  cooldown_until = ct + timedelta(hours=24)
                    elif consec_loss >= 3:  cooldown_until = ct + timedelta(hours=8)
                else:
                    consec_loss = 0
                current_trade = None
            continue

        # ── 연속 손절 쿨다운 ──
        if cooldown_until and ct < cooldown_until:
            continue

        # ── 진입 분석 ──
        snap_15m = df_15m.iloc[i-100:i+1]
        snap_4h  = df_4h_full.iloc[max(0, h4_idx-99):h4_idx+1]
        snap_1d  = df_1d_full.iloc[max(0, d1_idx-59):d1_idx+1]

        htf_bias = 'bullish'
        if not snap_4h.empty:
            last_h4  = snap_4h.iloc[-1]
            htf_bias = 'bullish' if last_h4['close'] >= last_h4['ema50'] else 'bearish'

        if use_external:
            mock_ext  = simulate_external_data(snap_15m, htf_bias)
            data_dict = {'15m': snap_15m, '4h': snap_4h, '1d': snap_1d, 'mock_external': mock_ext}
        else:
            # 외부 데이터 없이 순수 ICT 조건만 사용
            data_dict = {'15m': snap_15m, '4h': snap_4h, '1d': snap_1d}

        analysis = dm.analyze_entry(data_dict, symbol='BTC/USDT', current_time=ct)

        if analysis['action'] not in ['buy', 'sell']:
            continue

        action = analysis['action']

        # 기존과 동일한 추가 필터들
        h4_rsi = calc_rsi(snap_4h['close']) if len(snap_4h) >= 15 else 50.0
        if action == 'sell' and h4_rsi < 35: continue
        if action == 'buy'  and h4_rsi > 75: continue
        if not ict_engine.is_kill_zone(current_time=ct)['in_kill_zone'] \
                and analysis['confluence'] < min_confluence + 0.5:
            continue
        if len(snap_4h) >= 20 and not check_4h_momentum(snap_4h, action):
            continue

        # 포지션 오픈 (RR 고정 3:1)
        sl, _ = ict_engine.calculate_sl_tp(snap_15m, action)
        if not sl: continue

        ep = row['close']
        sl_dist = abs(ep - sl) / ep
        if sl_dist == 0: continue
        if not (0.0015 <= sl_dist <= 0.030): continue

        tp  = ep + (ep - sl) * 3.0 if action == 'buy' else ep - (sl - ep) * 3.0
        tp_dist = abs(tp - ep) / ep
        rr  = 3.0

        risk_amt = capital * RISK_PCT
        qty = risk_amt / (sl_dist * ep)
        if qty <= 0: continue

        if analysis.get('scalp_mode'):
            qty *= 0.5

        current_trade = {
            'side': action, 'entry_price': ep, 'entry_time': ct,
            'sl': sl, 'tp': tp, 'qty': qty,
            'confluence': analysis['confluence'],
            'scalp_mode': analysis.get('scalp_mode', False),
            'status': 'open',
        }

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
    wins = sum(1 for t in trades if t['result'] == 'profit')
    wr   = wins / n * 100

    peak = INITIAL_CAPITAL
    mdd  = 0.0
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
    print(f"  {'설정':<32} {'거래':>5}  {'승률':>6}  {'ROI':>8}  {'MDD':>6}  {'최종자본':>10}")
    print(f"  {'─'*78}")

    best_roi = max(r['roi'] for r in results)
    for r in results:
        marker = ' ◀ 최고' if r['roi'] == best_roi else ''
        print(f"  {r['label']:<32} {r['n']:>5}회  {r['wr']:>5.1f}%  "
              f"{r['roi']:>+7.1f}%  {r['mdd']:>5.1f}%  "
              f"{r['final']:>9,.0f}U{marker}")
    print(f"{'═'*80}")

    # 월별 상세 (두 전략 나란히)
    print(f"\n★ 월별 거래 비교")
    print(f"  {'월':>8}  {'거래(4.7)':>10}  {'승률':>6}  {'거래(4.0)':>10}  {'승률':>6}")
    monthly = {r['label']: defaultdict(list) for r in results}
    for r in results:
        for t in r['trades']:
            monthly[r['label']][t['entry_time'].strftime('%Y-%m')].append(t)

    all_months = sorted(set(
        m for r in results for m in monthly[r['label']].keys()
    ))
    for m in all_months:
        row_parts = [f"  {m}"]
        for r in results:
            mt  = monthly[r['label']].get(m, [])
            mw  = sum(1 for t in mt if t['result'] == 'profit')
            wr_m = mw / len(mt) * 100 if mt else 0
            row_parts.append(f"{len(mt):>8}회  {wr_m:>5.1f}%")
        print("  ".join(row_parts))

    print(f"{'═'*80}")


# ══════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════

if __name__ == '__main__':
    print(f"\n{'═'*80}")
    print(f"  메인 전략 컨플루언스 임계값 비교  |  BTC/USDT  |  1년  |  리스크 2.5%")
    print(f"  초기자본 {INITIAL_CAPITAL:.0f} USDT")
    print(f"{'═'*80}")

    fetcher = DataFetcher()
    result  = fetch_data(fetcher)
    if not result: exit()

    df_15m, df_4h, df_1d = result

    # 세 가지 설정 비교
    configs = [
        (4.7, 'A. min_confluence 4.7 (기존)',    True),
        (4.0, 'B. min_confluence 4.0 (완화)',    True),
        (3.7, 'C. 외부데이터 제거 (순수 ICT)',   False),
    ]

    all_results = []
    for threshold, label, use_ext in configs:
        trades, equity = run_main_strategy(df_15m, df_4h, df_1d, threshold, label, use_external=use_ext)
        all_results.append(calc_stats(trades, equity, label))

    print_results(all_results)

    # 위성 v3 기준점 출력 (메모리에서 참조)
    print(f"\n  📌 참고: 위성 v3 → 226회 / 승률 31.9% / ROI +78.7% / MDD 11.2%")
    print(f"{'═'*80}")
