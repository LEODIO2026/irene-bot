import sys, os, math
import pandas as pd
from datetime import datetime, timezone
from core.data_fetcher import DataFetcher
from core.ict_engine import ICTEngine

def load_data():
    fetcher = DataFetcher()
    symbol = 'BTC/USDT'
    limit_15m = 17520
    print("데이터 로딩 중...")
    df_15m = fetcher.fetch_ohlcv(symbol, '15m', limit_15m)
    st_time = df_15m['timestamp'].iloc[0]
    df_4h = fetcher.fetch_ohlcv(symbol, '4h', 1500)
    df_4h = df_4h[df_4h['timestamp'] >= st_time].reset_index(drop=True)
    df_1d = fetcher.fetch_ohlcv(symbol, '1d', 300)
    df_1d = df_1d[df_1d['timestamp'] >= st_time].reset_index(drop=True)
    return df_15m, df_4h, df_1d

def is_kill_zone(dt):
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    ts = pd.to_datetime(dt, unit='ms', utc=True)
    ny = ZoneInfo("America/New_York")
    now_ny = ts.astimezone(ny)
    hm = now_ny.hour * 100 + now_ny.minute
    if hm >= 2000:         return 'asia'
    if 200  <= hm < 500:   return 'london'
    if 830  <= hm < 1100:  return 'newyork_am'
    if 1330 <= hm < 1600:  return 'newyork_pm'
    return False

def check_trade(trade, row, rr):
    if not trade: return None
    t = trade.copy()
    high, low = float(row['high']), float(row['low'])
    if t['side'] == 'buy':
        if low <= t['sl']:
            t['result'] = 'loss'
            t['exit'] = t['sl']
            t['exit_time'] = row['timestamp']
            return t
        if high >= t['tp']:
            t['result'] = 'win'
            t['exit'] = t['tp']
            t['exit_time'] = row['timestamp']
            return t
    else:
        if high >= t['sl']:
            t['result'] = 'loss'
            t['exit'] = t['sl']
            t['exit_time'] = row['timestamp']
            return t
        if low <= t['tp']:
            t['result'] = 'win'
            t['exit'] = t['tp']
            t['exit_time'] = row['timestamp']
            return t
    return None

def score_to_risk(score):
    if score >= 1.5: return 0.03
    if score >= 1.0: return 0.02
    return 0.01

def ext_score(snap_15m, side):
    if len(snap_15m) < 10: return 0.0
    vol_mean = snap_15m['volume'].iloc[-10:].mean()
    vol_now = snap_15m['volume'].iloc[-1]
    s = 0.0
    if vol_now > vol_mean * 1.5: s += 0.5
    try:
        rsi_diff = float(snap_15m['close'].iloc[-1]) - float(snap_15m['close'].iloc[-5])
        if side == 'buy' and rsi_diff > 0: s += 0.5
        if side == 'sell' and rsi_diff < 0: s += 0.5
    except: pass
    return s

def simulate(df_15m, df_4h, df_1d, ict_engine, mode_ema=False, min_fvg_size=0.0, label=""):
    print(f"\n[{label}] 진행 중...")
    trades = []
    capital = 1000.0
    current_trade = None
    h4_idx = d1_idx = 0

    for i in range(200, len(df_15m)):
        row = df_15m.iloc[i]
        ct = row['timestamp']

        while h4_idx + 1 < len(df_4h) and df_4h.iloc[h4_idx+1]['timestamp'] <= ct: h4_idx += 1
        while d1_idx + 1 < len(df_1d) and df_1d.iloc[d1_idx+1]['timestamp'] <= ct: d1_idx += 1

        done = check_trade(current_trade, row, 3.0)
        if done:
            risk_amt = done['qty'] * abs(done['entry_price'] - done['sl'])
            pnl = risk_amt * 3.0 if done['result'] == 'win' else (-risk_amt if done['result'] == 'loss' else 0)
            capital += pnl
            trades.append(done)
            current_trade = None
            continue
        if current_trade: continue

        if not is_kill_zone(ct): continue

        snap_1d = df_1d.iloc[max(0, d1_idx-49): d1_idx+1]
        if len(snap_1d) < 30: continue
        
        # 1D ICT 구조
        swing_1d = ict_engine.detect_swing_structure(snap_1d, lookback=5)
        bias_1d = 'neutral'
        if swing_1d in ['bullish', 'strong_bullish']: bias_1d = 'bullish'
        elif swing_1d in ['bearish', 'strong_bearish']: bias_1d = 'bearish'
        if bias_1d == 'neutral':
            b = ict_engine.detect_bos_mss(snap_1d, swing_window=3)
            bias_1d = b['direction']
        if bias_1d == 'neutral': continue
        
        price_now = float(row['close'])
        
        # EMA Filter Check (Mode 2/3)
        if mode_ema:
            ema200 = snap_1d['close'].ewm(span=200, adjust=False).mean().iloc[-1]
            if (bias_1d == 'bullish' and price_now < ema200) or (bias_1d == 'bearish' and price_now > ema200):
                continue
            snap_4h = df_4h.iloc[max(0, h4_idx-49): h4_idx+1]
            ema20_4h = snap_4h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
            mom_4h = 'bullish' if float(snap_4h['close'].iloc[-1]) > ema20_4h else 'bearish'
            if mom_4h != bias_1d: continue

        side = 'buy' if bias_1d == 'bullish' else 'sell'
        snap_15m = df_15m.iloc[max(0, i-100): i+1]
        
        # 15m Sweep
        sweep_type = 'SSL_sweep' if side == 'buy' else 'BSL_sweep'
        sweeps = ict_engine.detect_liquidity_sweeps(snap_15m)
        recents = [s for s in sweeps if s['type'] == sweep_type and s['index'] >= len(snap_15m)-24]
        if not recents: continue
        s_idx = max(s['index'] for s in recents)

        # FVG Check + Size Threshold
        fvg_type = 'bullish' if side == 'buy' else 'bearish'
        fvgs = ict_engine.detect_fvg(snap_15m)
        valid_fvgs = [f for f in fvgs if f['type'] == fvg_type and f['index'] >= s_idx]
        matched_fvg = None
        for f in valid_fvgs:
            fvg_size = f['top'] - f['bottom']
            if fvg_size / price_now >= min_fvg_size:
                if f['bottom'] * 0.999 <= price_now <= f['top'] * 1.001:
                    matched_fvg = f
                    break
        if not matched_fvg: continue
        
        # Trade Setup
        score = ext_score(snap_15m, side)
        r_pct = score_to_risk(score)
        
        sl = matched_fvg['bottom'] if side == 'buy' else matched_fvg['top']
        if side == 'buy':
            if price_now <= sl: continue
            sl = sl * 0.999
            tp = price_now + (price_now - sl) * 3.0
        else:
            if price_now >= sl: continue
            sl = sl * 1.001
            tp = price_now - (sl - price_now) * 3.0
            
        risk_dist = abs(price_now - sl)
        if risk_dist / price_now > 0.05: continue
        qty = (capital * r_pct) / risk_dist
        
        current_trade = {
            'side': side, 'entry_price': price_now, 'sl': sl, 'tp': tp,
            'qty': qty, 'entry_time': ct, 'risk_pct': r_pct
        }

    wins = sum(1 for t in trades if t['result'] == 'win')
    wr = (wins / len(trades) * 100) if trades else 0.0
    roi = (capital - 1000) / 10
    print(f"[{label}] 거래: {len(trades)}회, 승률: {wr:.1f}%, ROI: {roi:+.1f}%, 최종잔고: {capital:.1f}U")
    return

if __name__ == '__main__':
    ict = ICTEngine()
    df_15m, df_4h, df_1d = load_data()
    simulate(df_15m, df_4h, df_1d, ict, mode_ema=False, min_fvg_size=0.001, label="C-1 (FVG 크기 0.1% 이상)")
    simulate(df_15m, df_4h, df_1d, ict, mode_ema=False, min_fvg_size=0.002, label="C-2 (FVG 크기 0.2% 이상)")
    simulate(df_15m, df_4h, df_1d, ict, mode_ema=False, min_fvg_size=0.003, label="C-3 (FVG 크기 0.3% 이상)")
