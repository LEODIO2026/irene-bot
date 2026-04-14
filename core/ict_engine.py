import pandas as pd
import numpy as np

class ICTEngine:
    def __init__(self):
        pass

    def detect_fvg(self, df):
        """
        Fair Value Gap (FVG) 탐지: 3개의 캔들 사이의 갭을 찾습니다.
        """
        fvgs = []
        for i in range(2, len(df)):
            # Bullish FVG (Gap Up between Candle 1 High and Candle 3 Low)
            if df.iloc[i-2]['high'] < df.iloc[i]['low']:
                fvg = {
                    'type': 'bullish',
                    'top': df.iloc[i]['low'],
                    'bottom': df.iloc[i-2]['high'],
                    'timestamp': df.iloc[i-1]['timestamp'],
                    'index': i-1
                }
                fvgs.append(fvg)
            
            # Bearish FVG (Gap Down between Candle 1 Low and Candle 3 High)
            elif df.iloc[i-2]['low'] > df.iloc[i]['high']:
                fvg = {
                    'type': 'bearish',
                    'top': df.iloc[i-2]['low'],
                    'bottom': df.iloc[i]['high'],
                    'timestamp': df.iloc[i-1]['timestamp'],
                    'index': i-1
                }
                fvgs.append(fvg)
        return fvgs

    def detect_mss(self, df, window=5):
        """
        Market Structure Shift (MSS) 탐지: 최근 고점/저점을 강하게 돌파하는지 확인.
        성능 최적화: 외부에서 계산된 swing_high/low를 활용하거나 효율적으로 계산합니다.
        """
        # swing_high/low가 없을 때만 계산 (슬라이스 복사 후 안전하게 처리)
        if 'swing_high' not in df.columns:
            df = df.copy()
            df['swing_high'] = df['high'].rolling(window=window, center=True).max()
            df['swing_low'] = df['low'].rolling(window=window, center=True).min()
            df['body_size'] = abs(df['close'] - df['open'])
            df['avg_body'] = df['body_size'].rolling(window=10).mean()

        mss_signals = []
        # 성능을 위해 iterrows 대신 iloc/values 접근 권장 (여기서는 가독성을 위해 최소한의 수정)
        for i in range(window, len(df)):
            prev_swing_high = df.iloc[i-1]['swing_high']
            prev_swing_low = df.iloc[i-1]['swing_low']
            
            if np.isnan(prev_swing_high): continue

            current_row = df.iloc[i]
            
            # Bullish MSS: 이전 Swing High를 종가로 돌파
            if current_row['close'] > prev_swing_high:
                if current_row['body_size'] > current_row['avg_body'] * 1.5:
                    mss_signals.append({'type': 'bullish', 'index': i, 'price': current_row['close'], 'timestamp': current_row['timestamp']})
            
            # Bearish MSS: 이전 Swing Low를 종가로 이탈
            elif current_row['close'] < prev_swing_low:
                if current_row['body_size'] > current_row['avg_body'] * 1.5:
                    mss_signals.append({'type': 'bearish', 'index': i, 'price': current_row['close'], 'timestamp': current_row['timestamp']})
                    
        return mss_signals

    def detect_liquidity_sweeps(self, df, lookback=20):
        """
        Liquidity Sweeps (유동성 사냥) 탐지.
        성능 최적화: 미리 계산된 롤링 max/min이 있으면 사용합니다.
        """
        use_precalc = 'roll_max_20' in df.columns
        sweeps = []
        
        for i in range(lookback, len(df)):
            current_row = df.iloc[i]
            
            if use_precalc:
                recent_max = current_row['roll_max_20']
                recent_min = current_row['roll_min_20']
            else:
                high_range = df['high'].iloc[i-lookback:i]
                low_range = df['low'].iloc[i-lookback:i]
                recent_max = high_range.max()
                recent_min = low_range.min()
            
            # Buy Side Liquidity (BSL) Sweep
            if current_row['high'] > recent_max and current_row['close'] < recent_max:
                sweeps.append({'type': 'BSL_sweep', 'index': i, 'timestamp': current_row['timestamp']})
                
            # Sell Side Liquidity (SSL) Sweep
            elif current_row['low'] < recent_min and current_row['close'] > recent_min:
                sweeps.append({'type': 'SSL_sweep', 'index': i, 'timestamp': current_row['timestamp']})
                
        return sweeps

    def detect_order_blocks(self, df, mss_signals):
        """
        Order Block (OB) 탐지: MSS가 발생하기 직전의 반대 방향 캔들 묶음.
        """
        obs = []
        for mss in mss_signals:
            idx = mss['index']
            if mss['type'] == 'bullish':
                # 상방 돌파 전 마지막 음봉(들)을 OB로 식별
                j = idx - 1
                while j > 0 and df.iloc[j]['close'] < df.iloc[j]['open']:
                    j -= 1
                ob = {
                    'type': 'bullish_OB',
                    'top': df.iloc[idx-1]['high'],
                    'bottom': df.iloc[idx-1]['low'],
                    'timestamp': df.iloc[idx-1]['timestamp']
                }
                obs.append(ob)
            elif mss['type'] == 'bearish':
                # 하방 돌파 전 마지막 양봉(들)을 OB로 식별
                j = idx - 1
                while j > 0 and df.iloc[j]['close'] > df.iloc[j]['open']:
                    j -= 1
                ob = {
                    'type': 'bearish_OB',
                    'top': df.iloc[idx-1]['high'],
                    'bottom': df.iloc[idx-1]['low'],
                    'timestamp': df.iloc[idx-1]['timestamp']
                }
                obs.append(ob)
        return obs

    # ═══════════════════════════════════════════════════
    #  시장 구조 분석: BOS/MSS + EMA 필터
    # ═══════════════════════════════════════════════════

    def detect_bos_mss(self, df, swing_window: int = 3) -> dict:
        """
        BOS(Break of Structure) / MSS(Market Structure Shift) 감지.

        - BOS Bullish : 종가가 직전 스윙 하이를 돌파 → 상승 구조
        - MSS Bearish : 종가 + 몸통이 직전 스윙 로우를 강하게 이탈 → 구조 전환

        Returns:
            {
                'direction' : 'bullish' | 'bearish' | 'neutral',
                'last_event': 'BOS' | 'MSS' | None,
                'level'     : float | None,   # 돌파/이탈된 스윙 레벨
                'reason'    : str,
            }
        """
        if len(df) < swing_window * 6:
            return {'direction': 'neutral', 'last_event': None, 'level': None, 'reason': '데이터 부족'}

        closes = df['close'].values
        highs  = df['high'].values
        lows   = df['low'].values
        opens  = df['open'].values
        w = swing_window

        # ── 피벗 고점/저점 감지 ──
        pivot_highs, pivot_lows = [], []
        for i in range(w, len(df) - w):
            if highs[i] == max(highs[i - w: i + w + 1]):
                pivot_highs.append((i, highs[i]))
            if lows[i] == min(lows[i - w: i + w + 1]):
                pivot_lows.append((i, lows[i]))

        if len(pivot_highs) < 2 or len(pivot_lows) < 2:
            return {'direction': 'neutral', 'last_event': None, 'level': None, 'reason': '피벗 부족'}

        # ── 상태 머신: 스윙 레벨 돌파 여부 순차 추적 ──
        direction  = 'neutral'
        last_event = None
        last_level = None

        ph_ptr = pl_ptr = 0

        for i in range(w, len(df)):
            # 이 캔들 이전의 가장 최신 스윙 포인트로 포인터 이동
            while ph_ptr + 1 < len(pivot_highs) and pivot_highs[ph_ptr + 1][0] < i:
                ph_ptr += 1
            while pl_ptr + 1 < len(pivot_lows) and pivot_lows[pl_ptr + 1][0] < i:
                pl_ptr += 1

            last_sh = pivot_highs[ph_ptr][1]
            last_sl = pivot_lows[pl_ptr][1]
            close_i = closes[i]
            open_i  = opens[i]
            body    = abs(close_i - open_i)
            avg_body = float(np.mean([abs(closes[j] - opens[j])
                                      for j in range(max(0, i - 10), i)])) if i > 0 else 1.0

            # BOS Bullish: 종가가 스윙 하이 돌파
            if close_i > last_sh:
                direction  = 'bullish'
                last_event = 'BOS'
                last_level = last_sh

            # MSS Bearish: 종가가 스윙 로우 이탈 (몸통 조건 — 음봉 필요)
            elif close_i < last_sl and close_i < open_i and body >= avg_body * 0.8:
                direction  = 'bearish'
                last_event = 'MSS'
                last_level = last_sl

        reason = (f'{last_event} @ {last_level:.2f}' if last_event and last_level
                  else '구조 미확정')
        return {'direction': direction, 'last_event': last_event,
                'level': last_level, 'reason': reason}

    # ═══════════════════════════════════════════════════
    #  시장 구조 분석: 스윙 구조 + ADX
    # ═══════════════════════════════════════════════════

    def calculate_adx(self, df, period: int = 14) -> float:
        """
        ADX (Average Directional Index) 계산.
        Returns:
            float: ADX 값 (0~100). 25 이상이면 추세 존재.
        """
        if len(df) < period * 2:
            return 0.0

        high  = df['high'].values
        low   = df['low'].values
        close = df['close'].values

        tr_list, pdm_list, ndm_list = [], [], []
        for i in range(1, len(df)):
            tr  = max(high[i] - low[i],
                      abs(high[i] - close[i-1]),
                      abs(low[i]  - close[i-1]))
            pdm = max(high[i] - high[i-1], 0) if high[i] - high[i-1] > low[i-1] - low[i] else 0
            ndm = max(low[i-1] - low[i],  0) if low[i-1] - low[i] > high[i] - high[i-1] else 0
            tr_list.append(tr); pdm_list.append(pdm); ndm_list.append(ndm)

        tr_s  = pd.Series(tr_list).ewm(span=period, adjust=False).mean()
        pdm_s = pd.Series(pdm_list).ewm(span=period, adjust=False).mean()
        ndm_s = pd.Series(ndm_list).ewm(span=period, adjust=False).mean()

        pdi = 100 * pdm_s / tr_s.replace(0, np.nan)
        ndi = 100 * ndm_s / tr_s.replace(0, np.nan)
        dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
        adx = dx.ewm(span=period, adjust=False).mean()

        val = adx.iloc[-1]
        return round(float(val) if not np.isnan(val) else 0.0, 2)

    def detect_swing_structure(self, df, swing_window: int = 5, lookback: int = 3) -> dict:
        """
        스윙 고점/저점의 흐름으로 시장 구조를 판단합니다.

        Returns:
            {
                'structure': 'bullish' | 'bearish' | 'sideways',
                'reason'   : str,
                'hh': bool, 'hl': bool, 'lh': bool, 'll': bool,
            }
        """
        if len(df) < swing_window * (lookback + 2):
            return {'structure': 'sideways', 'reason': '데이터 부족', 'hh': False, 'hl': False, 'lh': False, 'll': False}

        # 피벗 고점/저점 감지 (rolling max/min이 자기 자신인 캔들)
        roll_hi = df['high'].rolling(swing_window, center=True).max()
        roll_lo = df['low'].rolling(swing_window, center=True).min()

        pivot_highs = df['high'][df['high'] == roll_hi].dropna()
        pivot_lows  = df['low'][df['low']  == roll_lo].dropna()

        # 최근 lookback개 피벗만 사용
        ph = pivot_highs.iloc[-lookback:].values if len(pivot_highs) >= lookback else []
        pl = pivot_lows.iloc[-lookback:].values  if len(pivot_lows)  >= lookback else []

        if len(ph) < 2 or len(pl) < 2:
            return {'structure': 'sideways', 'reason': '피벗 부족', 'hh': False, 'hl': False, 'lh': False, 'll': False}

        # 스윙 구조 판단
        hh = bool(ph[-1] > ph[-2])   # 최근 고점이 이전 고점보다 높음
        hl = bool(pl[-1] > pl[-2])   # 최근 저점이 이전 저점보다 높음
        lh = bool(ph[-1] < ph[-2])   # 최근 고점이 이전 고점보다 낮음
        ll = bool(pl[-1] < pl[-2])   # 최근 저점이 이전 저점보다 낮음

        # 허용 오차: 0.3% 이내 차이는 Equal로 처리
        tol = 0.003
        if abs(ph[-1] - ph[-2]) / ph[-2] < tol:
            hh = lh = False  # Equal High
        if abs(pl[-1] - pl[-2]) / pl[-2] < tol:
            hl = ll = False  # Equal Low

        if hh and hl:
            structure = 'bullish'
            reason    = f'HH({ph[-2]:.0f}→{ph[-1]:.0f}) + HL({pl[-2]:.0f}→{pl[-1]:.0f})'
        elif lh and ll:
            structure = 'bearish'
            reason    = f'LH({ph[-2]:.0f}→{ph[-1]:.0f}) + LL({pl[-2]:.0f}→{pl[-1]:.0f})'
        elif hh and ll:
            structure = 'sideways'
            reason    = f'HH + LL (확장 박스권)'
        elif lh and hl:
            structure = 'sideways'
            reason    = f'LH + HL (수축 박스권)'
        else:
            structure = 'sideways'
            reason    = f'구조 불명확 (EQH/EQL 혼재)'

        return {'structure': structure, 'reason': reason, 'hh': hh, 'hl': hl, 'lh': lh, 'll': ll}

    # ═══════════════════════════════════════════════════
    #  ICT v2 업그레이드: 킬존 / 프리미엄-디스카운트 / OTE / 변위 강도
    # ═══════════════════════════════════════════════════

    def is_kill_zone(self, current_time=None):
        """
        특정 시각(또는 현재 시각)이 ICT 킬존(기관 활동 시간대)인지 판단합니다.
        
        Args:
            current_time (datetime, optional): 판단할 기준 시각 (UTC). None이면 현재 시각 사용.
        """
        from datetime import datetime, timezone
        if current_time is None:
            current_time = datetime.now(timezone.utc)
            
        hour = current_time.hour

        if 0 <= hour < 4:
            return {'in_kill_zone': True, 'session': '아시아 킬존', 'weight': 0.3}
        elif 7 <= hour < 10:
            return {'in_kill_zone': True, 'session': '런던 킬존', 'weight': 0.5}
        elif 12 <= hour < 15:
            return {'in_kill_zone': True, 'session': '뉴욕 킬존', 'weight': 0.5}
        elif 15 <= hour < 17:
            return {'in_kill_zone': True, 'session': '뉴욕 런치', 'weight': 0.3}
        else:
            return {'in_kill_zone': False, 'session': '킬존 외', 'weight': 0.0}

    def detect_premium_discount(self, df, lookback=50):
        """
        프리미엄/디스카운트 존 판별.
        Equilibrium(50%) 기준으로:
        - 상위 50% = 프리미엄 존 (매도만 적합)
        - 하위 50% = 디스카운트 존 (매수만 적합)

        Args:
            df: OHLCV DataFrame
            lookback: 레인지를 측정할 봉 수

        Returns:
            dict: {'zone': 'premium'|'discount'|'equilibrium', 'level': float (0~1)}
        """
        if df is None or len(df) < lookback:
            return {'zone': 'unknown', 'level': 0.5}

        recent = df.tail(lookback)
        range_high = recent['high'].max()
        range_low = recent['low'].min()
        current_price = df.iloc[-1]['close']

        if range_high == range_low:
            return {'zone': 'equilibrium', 'level': 0.5}

        # 0~1 사이 레벨 (0 = 바닥, 1 = 천장)
        level = (current_price - range_low) / (range_high - range_low)

        if level >= 0.7:
            return {'zone': 'premium', 'level': round(level, 3)}
        elif level <= 0.3:
            return {'zone': 'discount', 'level': round(level, 3)}
        else:
            return {'zone': 'equilibrium', 'level': round(level, 3)}

    def detect_ote_zone(self, df, lookback=20):
        """
        OTE (Optimal Trade Entry) 존 확인.
        최근 스윙 고/저 사이의 피보나치 62~79% 되돌림 구간을 찾습니다.

        - 상승 중 되돌림: 고점→저점의 Fib 0.62~0.79 구간에서 매수
        - 하락 중 되돌림: 저점→고점의 Fib 0.62~0.79 구간에서 매도

        Returns:
            dict: {'in_ote': bool, 'direction': str, 'fib_level': float}
        """
        if df is None or len(df) < lookback:
            return {'in_ote': False, 'direction': None, 'fib_level': 0}

        recent = df.tail(lookback)
        high_idx = recent['high'].idxmax()
        low_idx = recent['low'].idxmin()
        swing_high = recent['high'].max()
        swing_low = recent['low'].min()
        current_price = df.iloc[-1]['close']

        if swing_high == swing_low:
            return {'in_ote': False, 'direction': None, 'fib_level': 0}

        # 스윙이 상승 후 되돌림인지, 하락 후 되돌림인지 판단
        if high_idx > low_idx:
            # 저점 → 고점 → 현재 되돌림 (불리시 OTE)
            fib_range = swing_high - swing_low
            fib_62 = swing_high - fib_range * 0.618
            fib_79 = swing_high - fib_range * 0.786
            fib_level = (swing_high - current_price) / fib_range if fib_range > 0 else 0

            if fib_79 <= current_price <= fib_62:
                return {'in_ote': True, 'direction': 'bullish', 'fib_level': round(fib_level, 3)}
        else:
            # 고점 → 저점 → 현재 되돌림 (베어리시 OTE)
            fib_range = swing_high - swing_low
            fib_62 = swing_low + fib_range * 0.618
            fib_79 = swing_low + fib_range * 0.786
            fib_level = (current_price - swing_low) / fib_range if fib_range > 0 else 0

            if fib_62 <= current_price <= fib_79:
                return {'in_ote': True, 'direction': 'bearish', 'fib_level': round(fib_level, 3)}

        return {'in_ote': False, 'direction': None, 'fib_level': round((current_price - swing_low) / (swing_high - swing_low), 3) if swing_high != swing_low else 0}

    def calculate_displacement_strength(self, df, mss_signals):
        """
        MSS를 일으킨 변위(displacement) 캔들의 강도를 측정합니다.

        강도 지표:
        - 몸통 크기 vs 평균의 비율
        - 꼬리 대비 몸통 비율 (꼬리가 짧을수록 강한 변위)

        Returns:
            list[dict]: 각 MSS에 대한 강도 점수
        """
        results = []
        if df is None or len(df) < 10:
            return results

        avg_body = abs(df['close'] - df['open']).rolling(window=20).mean()

        for mss in mss_signals:
            idx = mss['index']
            if idx >= len(df):
                continue

            candle = df.iloc[idx]
            body = abs(candle['close'] - candle['open'])
            full_range = candle['high'] - candle['low']

            # 몸통/평균 비율 (2.0 이상이면 강력한 변위)
            avg = avg_body.iloc[idx] if idx < len(avg_body) and not pd.isna(avg_body.iloc[idx]) else body
            body_ratio = body / avg if avg > 0 else 1.0

            # 몸통/전체동 비율 (0.8 이상이면 거의 꼬리 없는 강한 캔들)
            body_fill = body / full_range if full_range > 0 else 0

            # 종합 강도 (0~1 스케일)
            strength = min(1.0, (body_ratio / 3.0) * 0.6 + body_fill * 0.4)

            results.append({
                'index': idx,
                'type': mss['type'],
                'body_ratio': round(body_ratio, 2),
                'body_fill': round(body_fill, 2),
                'strength': round(strength, 3),
                'is_strong': body_ratio >= 2.0 and body_fill >= 0.6
            })

        return results

    def analyze_4h_structure(self, df_4h, bias):
        """
        4시간봉의 OB와 FVG를 분석하여 현재가가 4H 핵심 레벨
        근처에 있는지 확인합니다. 4H 레벨은 15m보다 훨씬 강력합니다.

        Returns:
            dict: {'has_4h_ob': bool, 'has_4h_fvg': bool, 'details': str}
        """
        result = {'has_4h_ob': False, 'has_4h_fvg': False, 'details': ''}

        if df_4h is None or len(df_4h) < 30:
            result['details'] = '4H 데이터 부족'
            return result

        current_price = df_4h.iloc[-1]['close']

        # 4H FVG 탐지
        fvgs = self.detect_fvg(df_4h)
        recent_fvgs = [f for f in fvgs if f['index'] >= len(df_4h) - 15]

        if bias == 'bullish':
            bull_fvgs = [f for f in recent_fvgs if f['type'] == 'bullish']
            in_fvg = any(f['bottom'] <= current_price <= f['top'] for f in bull_fvgs)
            near_fvg = any(abs(current_price - f['top']) / current_price < 0.008 for f in bull_fvgs)
            if in_fvg or near_fvg:
                result['has_4h_fvg'] = True
        elif bias == 'bearish':
            bear_fvgs = [f for f in recent_fvgs if f['type'] == 'bearish']
            in_fvg = any(f['bottom'] <= current_price <= f['top'] for f in bear_fvgs)
            near_fvg = any(abs(current_price - f['bottom']) / current_price < 0.008 for f in bear_fvgs)
            if in_fvg or near_fvg:
                result['has_4h_fvg'] = True

        # 4H OB 탐지
        mss_4h = self.detect_mss(df_4h)
        obs_4h = self.detect_order_blocks(df_4h, mss_4h)

        if bias == 'bullish':
            bull_obs = [o for o in obs_4h if o['type'] == 'bullish_OB']
            in_ob = any(o['bottom'] <= current_price <= o['top'] * 1.005 for o in bull_obs)
            if in_ob:
                result['has_4h_ob'] = True
        elif bias == 'bearish':
            bear_obs = [o for o in obs_4h if o['type'] == 'bearish_OB']
            in_ob = any(o['bottom'] * 0.995 <= current_price <= o['top'] for o in bear_obs)
            if in_ob:
                result['has_4h_ob'] = True

        parts = []
        if result['has_4h_fvg']:
            parts.append('4H FVG')
        if result['has_4h_ob']:
            parts.append('4H OB')
        result['details'] = ' + '.join(parts) if parts else '4H 레벨 없음'

        return result

    @staticmethod
    def _calc_atr(df, period=14):
        """ATR(Average True Range) 계산."""
        high  = df['high']
        low   = df['low']
        close = df['close']
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs()
        ], axis=1).max(axis=1)
        return tr.tail(period).mean()

    @staticmethod
    def _calc_adx(df, period=14):
        """
        ADX(Average Directional Index) 계산.
        - ADX < 20: 횡보장 (진입 위험)
        - ADX 20~25: 약한 트렌드
        - ADX > 25: 강한 트렌드 (진입 유리)
        """
        if len(df) < period * 2:
            return 20.0

        high  = df['high'].values.astype(float)
        low   = df['low'].values.astype(float)
        close = df['close'].values.astype(float)

        tr_arr, plus_dm_arr, minus_dm_arr = [], [], []
        for i in range(1, len(high)):
            h_diff = high[i] - high[i-1]
            l_diff = low[i-1] - low[i]
            tr = max(high[i] - low[i],
                     abs(high[i] - close[i-1]),
                     abs(low[i]  - close[i-1]))
            tr_arr.append(tr)
            plus_dm_arr.append(h_diff if h_diff > l_diff and h_diff > 0 else 0.0)
            minus_dm_arr.append(l_diff if l_diff > h_diff and l_diff > 0 else 0.0)

        def smooth(arr, n):
            s = sum(arr[:n])
            result = [s]
            for v in arr[n:]:
                s = s - s / n + v
                result.append(s)
            return result

        atr_s    = smooth(tr_arr,       period)
        plus_s   = smooth(plus_dm_arr,  period)
        minus_s  = smooth(minus_dm_arr, period)

        dx_arr = []
        for a, p, m in zip(atr_s, plus_s, minus_s):
            if a == 0:
                dx_arr.append(0.0)
                continue
            plus_di  = 100 * p / a
            minus_di = 100 * m / a
            denom = plus_di + minus_di
            dx_arr.append(100 * abs(plus_di - minus_di) / denom if denom > 0 else 0.0)

        if len(dx_arr) < period:
            return 20.0
        adx = sum(dx_arr[-period:]) / period
        return round(adx, 2)

    def detect_eqh_eql(self, df, lookback=40, tolerance=0.0025):
        """
        Equal Highs (EQH) / Equal Lows (EQL) 유동성 풀 감지.
        서로 허용 오차(tolerance) 이내인 고점/저점 쌍 → 기관 유동성 집적 구간.

        Returns:
            dict: {'eqh': [price, ...], 'eql': [price, ...]}
        """
        if df is None or len(df) < lookback:
            return {'eqh': [], 'eql': []}

        recent = df.tail(lookback)
        highs  = recent['high'].values
        lows   = recent['low'].values

        eqh, eql = [], []

        for i in range(len(highs) - 1):
            for j in range(i + 2, len(highs)):  # 인접 캔들 제외
                if highs[i] > 0 and abs(highs[i] - highs[j]) / highs[i] < tolerance:
                    eqh.append(round((highs[i] + highs[j]) / 2, 2))

        for i in range(len(lows) - 1):
            for j in range(i + 2, len(lows)):
                if lows[i] > 0 and abs(lows[i] - lows[j]) / lows[i] < tolerance:
                    eql.append(round((lows[i] + lows[j]) / 2, 2))

        # 중복 클러스터링 (근접한 레벨은 평균값 하나로)
        def cluster(levels, tol=0.003):
            if not levels:
                return []
            levels = sorted(set(levels))
            clusters, cur = [], [levels[0]]
            for v in levels[1:]:
                if abs(v - cur[-1]) / cur[-1] < tol:
                    cur.append(v)
                else:
                    clusters.append(round(sum(cur) / len(cur), 2))
                    cur = [v]
            clusters.append(round(sum(cur) / len(cur), 2))
            return clusters

        return {'eqh': cluster(eqh), 'eql': cluster(eql)}

    def calculate_sl_tp(self, df, side, buffer_pct=0.001, min_rr=2.0):
        """
        ICT 구조 기반 SL/TP 자동 계산.
        - SL: 스윕 구조 저점/고점 + 버퍼 (구조적 레벨 그대로)
        - TP: 유동성 풀 기반이되, 최소 RR 2.0 보장
        SL 최솟값(0.5%) / 최댓값(2.0%) 필터는 backtester.open_trade에서 처리
        """
        current_price = df.iloc[-1]['close']

        sweeps      = self.detect_liquidity_sweeps(df)
        mss_signals = self.detect_mss(df)
        obs         = self.detect_order_blocks(df, mss_signals)

        lookback    = min(20, len(df))
        recent_high = df['high'].iloc[-lookback:].max()
        recent_low  = df['low'].iloc[-lookback:].min()

        sl, tp = None, None

        if side == 'buy':
            # SL: 최근 SSL 스윕 저점 아래
            ssl_sweeps = [s for s in sweeps if s['type'] == 'SSL_sweep']
            sl_base    = df.iloc[ssl_sweeps[-1]['index']]['low'] if ssl_sweeps else recent_low
            sl         = round(sl_base * (1 - buffer_pct), 2)

            sl_dist  = current_price - sl
            min_tp   = current_price + sl_dist * min_rr

            # TP: 최소 RR 이상의 가장 가까운 유동성 풀
            bsl_sweeps = [s for s in sweeps if s['type'] == 'BSL_sweep']
            tp_cands   = [df.iloc[s['index']]['high'] for s in bsl_sweeps
                          if df.iloc[s['index']]['high'] >= min_tp]
            if recent_high >= min_tp:
                tp_cands.append(recent_high)
            for o in obs:
                if o['type'] == 'bullish_OB' and o['top'] >= min_tp:
                    tp_cands.append(o['top'])
            tp = round(min(tp_cands), 2) if tp_cands else round(min_tp, 2)

        elif side == 'sell':
            # SL: 최근 BSL 스윕 고점 위
            bsl_sweeps = [s for s in sweeps if s['type'] == 'BSL_sweep']
            sl_base    = df.iloc[bsl_sweeps[-1]['index']]['high'] if bsl_sweeps else recent_high
            sl         = round(sl_base * (1 + buffer_pct), 2)

            sl_dist  = sl - current_price
            min_tp   = current_price - sl_dist * min_rr

            # TP: 최소 RR 이상의 가장 가까운 유동성 풀
            ssl_sweeps = [s for s in sweeps if s['type'] == 'SSL_sweep']
            tp_cands   = [df.iloc[s['index']]['low'] for s in ssl_sweeps
                          if df.iloc[s['index']]['low'] <= min_tp]
            if recent_low <= min_tp:
                tp_cands.append(recent_low)
            for o in obs:
                if o['type'] == 'bearish_OB' and o['bottom'] <= min_tp:
                    tp_cands.append(o['bottom'])
            tp = round(max(tp_cands), 2) if tp_cands else round(min_tp, 2)

        # ── 최종 방향 검증 ─────────────────────────
        if side == 'buy':
            if sl and sl >= current_price: sl = round(current_price * (1 - 0.005), 2)
            if tp and tp <= current_price: tp = round(current_price * (1 + 0.01),  2)
        elif side == 'sell':
            if sl and sl <= current_price: sl = round(current_price * (1 + 0.005), 2)
            if tp and tp >= current_price: tp = round(current_price * (1 - 0.01),  2)

        return sl, tp


if __name__ == "__main__":
    # 테스트 코드 (더미 데이터 필요 시 생성 가능)
    print("아이린: ICT 엔진 모듈 테스트 준비 완료 (실제 데이터 연동 필요)")

