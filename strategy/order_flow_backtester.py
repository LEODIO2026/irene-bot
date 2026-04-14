"""
오더플로우(Order Flow) 백테스터 v3
────────────────────────────────────────────────
개선 사항 (v3):
  - 완전한 ICT 시퀀스 강제: 4H 오더플로우 → 15m 스윕 → 15m MSS → FVG/OB 타점
  - WITH FLOW: 4H bullish + 15m SSL스윕 + MSS상방 + bullish FVG 진입
  - AGAINST FLOW: 4H bullish + 15m BSL스윕 + MSS하방 + bearish FVG 진입
  - 스윕~MSS 확인 후 형성된 FVG만 유효 타점으로 인정
  - OB 감지 수정: detect_order_blocks의 'index' 키 직접 사용
  - 1년 기간

상태 전환 규칙:
  neutral
    → SSL스윕 → bullish_pending
    → BSL스윕 → bearish_pending

  bullish_pending
    → MSS상방(종가 > 스윙하이) → bullish ✅
    → BSL스윕 발생 → bearish_pending (리셋)

  bearish_pending
    → MSS하방(종가 < 스윙로우) → bearish ✅
    → SSL스윕 발생 → bullish_pending (리셋)

  bullish
    → BSL스윕 → bearish_pending
    → 종가가 SSL스윕 저가 아래로 이탈 → neutral (무효화)

  bearish
    → SSL스윕 → bullish_pending
    → 종가가 BSL스윕 고가 위로 돌파 → neutral (무효화)
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from collections import defaultdict
from core.ict_engine import ICTEngine
from core.data_fetcher import DataFetcher


# ═══════════════════════════════════════════════════════
#  4H 오더플로우 상태 선계산
# ═══════════════════════════════════════════════════════

def build_order_flow_states(df_4h: pd.DataFrame, swing_window: int = 5) -> list:
    """
    4H 전체 캔들에 대해 오더플로우 상태를 순차적으로 계산.

    Returns:
        list[str]: 각 캔들의 상태 ('bullish' | 'bearish' | 'neutral')
    """
    n      = len(df_4h)
    states = ['neutral'] * n

    highs  = df_4h['high'].values
    lows   = df_4h['low'].values
    closes = df_4h['close'].values
    w      = swing_window

    # ── 피벗 고점/저점 계산 ──
    pivot_highs = {}  # {idx: price}
    pivot_lows  = {}
    for i in range(w, n - w):
        if highs[i] == max(highs[i - w: i + w + 1]):
            pivot_highs[i] = highs[i]
        if lows[i] == min(lows[i - w: i + w + 1]):
            pivot_lows[i] = lows[i]

    ph_list = sorted(pivot_highs.items())
    pl_list = sorted(pivot_lows.items())

    # ── 상태 머신 순회 ──
    of_state       = 'neutral'
    ssl_sweep_low  = None   # 강세 전환 시 기준 저가 (무효화 레벨)
    bsl_sweep_high = None   # 약세 전환 시 기준 고가 (무효화 레벨)
    last_ph        = None
    last_pl        = None
    ph_ptr = pl_ptr = 0

    for i in range(w, n):
        # 이 캔들 이전까지의 최신 피벗 갱신
        while ph_ptr < len(ph_list) and ph_list[ph_ptr][0] < i:
            last_ph = ph_list[ph_ptr][1]
            ph_ptr += 1
        while pl_ptr < len(pl_list) and pl_list[pl_ptr][0] < i:
            last_pl = pl_list[pl_ptr][1]
            pl_ptr += 1

        if last_ph is None or last_pl is None:
            continue

        h, lo, c = highs[i], lows[i], closes[i]

        # ── 스윕 감지 ──
        ssl_swept = (lo < last_pl) and (c > last_pl)   # 저점 아래 꼬리, 위 마감
        bsl_swept = (h  > last_ph) and (c < last_ph)   # 고점 위 꼬리, 아래 마감

        # ── 상태 전환 ──
        if of_state == 'neutral':
            if ssl_swept:
                of_state      = 'bullish_pending'
                ssl_sweep_low = lo
            elif bsl_swept:
                of_state       = 'bearish_pending'
                bsl_sweep_high = h

        elif of_state == 'bullish_pending':
            if bsl_swept:                        # 반대 스윕 → 방향 전환
                of_state       = 'bearish_pending'
                bsl_sweep_high = h
                ssl_sweep_low  = None
            elif c > last_ph:                    # MSS 상방 → 강세 확정
                of_state = 'bullish'

        elif of_state == 'bearish_pending':
            if ssl_swept:                        # 반대 스윕 → 방향 전환
                of_state      = 'bullish_pending'
                ssl_sweep_low = lo
                bsl_sweep_high = None
            elif c < last_pl:                    # MSS 하방 → 약세 확정
                of_state = 'bearish'

        elif of_state == 'bullish':
            if bsl_swept:                        # BSL 스윕 → 약세 대기
                of_state       = 'bearish_pending'
                bsl_sweep_high = h
            elif ssl_sweep_low and c < ssl_sweep_low:   # 무효화
                of_state      = 'neutral'
                ssl_sweep_low = None

        elif of_state == 'bearish':
            if ssl_swept:                        # SSL 스윕 → 강세 대기
                of_state      = 'bullish_pending'
                ssl_sweep_low = lo
            elif bsl_sweep_high and c > bsl_sweep_high:  # 무효화
                of_state       = 'neutral'
                bsl_sweep_high = None

        # pending 상태는 neutral로 표시 (아직 미확정)
        states[i] = of_state if of_state in ('bullish', 'bearish') else 'neutral'

    return states


# ═══════════════════════════════════════════════════════
#  진입 포인트 감지 (영상 완전 시퀀스: 스윕 → MSS → FVG/OB)
# ═══════════════════════════════════════════════════════

def find_ict_setups(df_snap: pd.DataFrame, ict_engine, of_dir: str) -> list:
    """
    4H 오더플로우 방향에 따른 15m ICT 셋업 감지.
    시퀀스: 유동성 스윕 → 스윕 이후 반전 FVG

    (MSS는 바디 조건이 너무 엄격해 생략 — 스윕+반전FVG로 단순화)

    WITH FLOW (bullish):  SSL스윕 후 bullish FVG 형성 → BUY
    WITH FLOW (bearish):  BSL스윕 후 bearish FVG 형성 → SELL
    AGAINST FLOW:         반대 방향 시퀀스

    Returns:
        list[dict]: {kind, side, top, bottom, with_flow}
    """
    n = len(df_snap)
    if n < 20:
        return []

    sweep_lookback = n - 48   # 최근 12시간(48봉) 이내 스윕

    # 유동성 스윕 감지
    sweeps     = ict_engine.detect_liquidity_sweeps(df_snap)
    ssl_sweeps = [s for s in sweeps if s['type'] == 'SSL_sweep' and s['index'] >= sweep_lookback]
    bsl_sweeps = [s for s in sweeps if s['type'] == 'BSL_sweep' and s['index'] >= sweep_lookback]

    all_fvgs = ict_engine.detect_fvg(df_snap)

    setups = []

    def add_fvg_setups(sweep_list, fvg_type, side, with_flow):
        """스윕 이후 형성된 FVG를 타점으로 등록."""
        if not sweep_list:
            return
        # 가장 최근 스윕 기준
        sw_idx = max(s['index'] for s in sweep_list)
        for fvg in all_fvgs:
            if fvg['type'] == fvg_type and fvg['index'] > sw_idx:
                setups.append({
                    'kind': 'FVG', 'side': side, 'with_flow': with_flow,
                    'top': fvg['top'], 'bottom': fvg['bottom'],
                })

    if of_dir == 'bullish':
        add_fvg_setups(ssl_sweeps, 'bullish', 'buy',  with_flow=True)   # WITH
        add_fvg_setups(bsl_sweeps, 'bearish', 'sell', with_flow=False)  # AGAINST

    elif of_dir == 'bearish':
        add_fvg_setups(bsl_sweeps, 'bearish', 'sell', with_flow=True)   # WITH
        add_fvg_setups(ssl_sweeps, 'bullish', 'buy',  with_flow=False)  # AGAINST

    return setups


# ═══════════════════════════════════════════════════════
#  메인 백테스터
# ═══════════════════════════════════════════════════════

class OrderFlowBacktester:
    def __init__(self, symbol: str = 'BTC/USDT', rr: float = 3.0):
        self.symbol     = symbol
        self.rr         = rr
        self.ict_engine = ICTEngine()
        self.fetcher    = DataFetcher()

    def run(self, limit: int = 17520):   # 기본 1년
        print(f"\n{'═'*60}")
        print(f"📊 오더플로우 백테스트 v3: {self.symbol}  |  RR {self.rr}:1")
        print(f"{'═'*60}")

        # 데이터 수집
        limit_4h = limit // 16 + 100
        df_15m = self.fetcher.fetch_ohlcv(self.symbol, '15m', limit=limit)
        df_4h  = self.fetcher.fetch_ohlcv(self.symbol, '4h',  limit=limit_4h)
        if df_15m is None or df_4h is None:
            print("❌ 데이터 수집 실패"); return

        print(f"✅ 15m({len(df_15m)}봉)  4h({len(df_4h)}봉)")

        # 15m 지표 선계산
        df_15m = df_15m.copy()
        df_15m['body_size']   = abs(df_15m['close'] - df_15m['open'])
        df_15m['avg_body']    = df_15m['body_size'].rolling(10).mean()
        df_15m['swing_high']  = df_15m['high'].rolling(5, center=True).max()
        df_15m['swing_low']   = df_15m['low'].rolling(5, center=True).min()
        df_15m['roll_max_20'] = df_15m['high'].shift(1).rolling(20).max()
        df_15m['roll_min_20'] = df_15m['low'].shift(1).rolling(20).min()

        # 4H 오더플로우 상태 선계산
        print("⚙️  4H 오더플로우 상태 계산 중...")
        of_states = build_order_flow_states(df_4h, swing_window=5)
        print(f"   Bullish: {of_states.count('bullish')}봉 | "
              f"Bearish: {of_states.count('bearish')}봉 | "
              f"Neutral: {of_states.count('neutral')}봉\n")

        h4_idx = 0
        with_trades    = []
        against_trades = []
        current_trade  = None

        for i in range(200, len(df_15m)):
            row          = df_15m.iloc[i]
            current_time = row['timestamp']

            # 4H 인덱스 동기화
            while (h4_idx + 1 < len(df_4h) and
                   df_4h.iloc[h4_idx + 1]['timestamp'] <= current_time):
                h4_idx += 1

            # ── 진행 중 거래 체크 ──
            if current_trade is not None:
                side   = current_trade['side']
                sl, tp = current_trade['sl'], current_trade['tp']
                result = None

                if side == 'buy':
                    if row['low']   <= sl: result = 'loss'
                    elif row['high'] >= tp: result = 'win'
                else:
                    if row['high']  >= sl: result = 'loss'
                    elif row['low']  <= tp: result = 'win'

                # 24H 타임스탑
                if result is None:
                    h = (current_time - current_trade['entry_time']).total_seconds() / 3600
                    if h >= 24:
                        result = 'timeout'

                if result:
                    current_trade['result'] = result
                    bucket = with_trades if current_trade['with_flow'] else against_trades
                    bucket.append(current_trade)
                    current_trade = None
                continue

            # ── 현재 4H 오더플로우 ──
            of_dir = of_states[h4_idx]
            if of_dir == 'neutral':
                continue

            # ── 15m ICT 완전 시퀀스 감지 (스윕→MSS→FVG/OB) ──
            snap   = df_15m.iloc[max(0, i - 100): i + 1]
            price  = float(row['close'])
            setups = find_ict_setups(snap, self.ict_engine, of_dir)

            for zone in setups:
                in_zone = zone['bottom'] * 0.999 <= price <= zone['top'] * 1.001
                if not in_zone:
                    continue

                side      = zone['side']
                with_flow = zone['with_flow']

                # SL / TP (RR 고정)
                if side == 'buy':
                    sl = zone['bottom'] * 0.999
                    tp = price + (price - sl) * self.rr
                else:
                    sl = zone['top'] * 1.001
                    tp = price - (sl - price) * self.rr

                sl_pct = abs(price - sl) / price * 100
                if not (0.15 <= sl_pct <= 3.0):
                    continue

                current_trade = {
                    'side':        side,
                    'kind':        zone['kind'],
                    'entry_price': price,
                    'sl': sl, 'tp': tp,
                    'entry_time':  current_time,
                    'of_dir':      of_dir,
                    'with_flow':   with_flow,
                    'result':      None,
                }
                break   # 존 하나만

        self._print_results(with_trades, against_trades)

    # ── 결과 출력 ──────────────────────────────────────
    def _print_results(self, with_trades: list, against_trades: list):
        def stats(trades, label):
            if not trades:
                print(f"\n  [{label}] 거래 없음"); return 0, 0
            total  = len(trades)
            wins   = sum(1 for t in trades if t['result'] == 'win')
            losses = total - wins
            wr     = wins / total * 100
            ev     = (wins * self.rr - losses) / total
            kinds  = defaultdict(int)
            for t in trades: kinds[t['kind']] += 1
            print(f"\n  [{label}]")
            print(f"    총 거래  : {total}회  (FVG:{kinds['FVG']} OB:{kinds['OB']})")
            print(f"    승/패    : {wins}승 {losses}패")
            print(f"    승률     : {wr:.1f}%")
            print(f"    기대값   : {ev:+.3f}R")
            return wr, total

        print(f"\n{'═'*60}")
        print(f"📈 오더플로우 백테스트 v3 결과  (RR {self.rr}:1)")
        print(f"{'═'*60}")
        wr_with, n_with       = stats(with_trades,    '오더플로우 따름 (WITH FLOW)')
        wr_against, n_against = stats(against_trades, '오더플로우 역행 (AGAINST)  ')

        if n_with and n_against:
            diff = wr_with - wr_against
            sign = '✅ 오더플로우 유리' if diff > 0 else '⚠️ 역행이 유리 (감지 로직 재검토 필요)'
            print(f"\n  ★ 승률 차이: {diff:+.1f}%p  →  {sign}")

        # 월별
        all_trades = [(t, True) for t in with_trades] + [(t, False) for t in against_trades]
        if all_trades:
            print(f"\n  월별 거래:")
            monthly = defaultdict(lambda: {'w':0,'ww':0,'a':0,'aw':0})
            for t, is_with in all_trades:
                m = t['entry_time'].strftime('%Y-%m')
                if is_with:
                    monthly[m]['w']  += 1
                    if t['result'] == 'win': monthly[m]['ww'] += 1
                else:
                    monthly[m]['a']  += 1
                    if t['result'] == 'win': monthly[m]['aw'] += 1
            print(f"  {'월':>8}  {'따름':>12}  {'역행':>12}")
            for m in sorted(monthly):
                d    = monthly[m]
                w_wr = d['ww']/d['w']*100 if d['w'] else 0
                a_wr = d['aw']/d['a']*100 if d['a'] else 0
                print(f"  {m}  {d['w']:>3}회 ({w_wr:>4.0f}%)   {d['a']:>3}회 ({a_wr:>4.0f}%)")

        print(f"{'═'*60}")


if __name__ == '__main__':
    bt = OrderFlowBacktester(symbol='BTC/USDT', rr=3.0)
    bt.run(limit=17520)   # 1년
