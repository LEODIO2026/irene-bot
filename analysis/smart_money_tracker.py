"""
아이린(Irene) v3 — 💎 스마트 머니 추적 엔진 (Smart Money Tracker)
──────────────────────────────────────────────────────────────
"세력의 알고리즘을 예측하고 그들의 행동을 읽는다."

분석 항목:
1. OI 급변 감지 — 세력의 포지션 구축/청산 포착
2. CVD(누적 거래량 델타) — 실제 매수·매도 압력 추정
3. CVD 다이버전스 — 가격과 CVD의 괴리 → 반전 신호
4. 청산 클러스터 추정 — 대규모 청산이 임박한 가격대

최대 점수: 1.0/10.0
"""

import requests
import time
import numpy as np


class SmartMoneyTracker:
    def __init__(self, fetcher=None):
        """
        Args:
            fetcher: DataFetcher 인스턴스
        """
        self.fetcher = fetcher
        self._oi_cache = {}

    # ─── OI 히스토리 조회 (DataFetcher 사용) ────────────────
    def fetch_oi_history(self, symbol, interval='1h', limit=24):
        """
        DataFetcher를 통해 OI 히스토리를 가져옵니다.
        """
        if self.fetcher:
            return self.fetcher.fetch_oi_history(symbol, interval, limit)
        return []

    # ─── OI 급변 및 세력 의도 감지 ───────────────────────────
    def detect_smart_money_move(self, symbol, current_price, is_sweep=False):
        """
        OI 변화와 가격 움직임을 결합하여 세력의 의도를 파악합니다.
        - 가격 Sweep + OI 증가 = 세력이 해당 가격대에서 물량을 받아먹음 (Absorption)
        - 가격 추세 + OI 증가 = 세력이 추세 방향으로 포지션을 구축 중 (Accumulation)
        - 가격 추세 + OI 감소 = 세력이 수익 실현 중 (Distribution/Unwinding)
        """
        oi_data = self.fetch_oi_history(symbol, interval='1h', limit=6)
        if len(oi_data) < 2:
            return {'score': 0, 'intent': 'neutral', 'change_pct': 0}

        latest_oi = oi_data[-1]['oi']
        prev_oi = oi_data[-2]['oi']
        change_pct = ((latest_oi - prev_oi) / prev_oi) * 100 if prev_oi > 0 else 0

        intent = 'neutral'
        score = 0.0

        if change_pct >= 5:  # 5% 이상 유의미한 증가
            if is_sweep:
                intent = 'absorption'  # 유동성 사냥 구간에서의 흡수
                score = 0.8
            else:
                intent = 'accumulation' # 일반적인 포지션 구축
                score = 0.5
        elif change_pct <= -5: # 5% 이상 유의미한 감소
            intent = 'unwinding'
            score = 0.2

        return {
            'score': score,
            'intent': intent,
            'change_pct': round(change_pct, 2),
            'latest_oi': latest_oi
        }

    # ─── CVD (누적 거래량 델타) 계산 ─────────────────────────
    @staticmethod
    def calculate_cvd(df):
        """
        OHLCV에서 CVD(Cumulative Volume Delta)를 추정합니다.
        """
        if df is None or len(df) < 5:
            return np.array([])

        deltas = []
        for _, row in df.iterrows():
            full_range = row['high'] - row['low']
            if full_range == 0:
                deltas.append(0)
                continue

            buy_pct = (row['close'] - row['low']) / full_range
            sell_pct = 1 - buy_pct
            
            # 거래량 가중치 적용 (몸통이 클수록 신뢰도 높음)
            body_ratio = abs(row['close'] - row['open']) / full_range
            delta = (row['volume'] * (buy_pct - sell_pct)) * body_ratio
            deltas.append(delta)

        return np.cumsum(deltas)

    # ─── CVD 다이버전스 탐지 ──────────────────────────────────
    def detect_cvd_divergence(self, df, lookback=20):
        """
        가격과 CVD 사이의 다이버전스를 탐지합니다.
        """
        if df is None or len(df) < lookback:
            return {'has_divergence': False, 'type': None, 'strength': 0}

        cvd = self.calculate_cvd(df)
        if len(cvd) == 0:
            return {'has_divergence': False, 'type': None, 'strength': 0}

        # 최근 고/저점 비교 방식으로 정밀화
        price_recent = df.tail(lookback)['close']
        cvd_recent = cvd[-lookback:]

        p_max_idx = price_recent.idxmax()
        p_min_idx = price_recent.idxmin()
        
        # 실제 인덱스로 변환
        relative_p_max = len(df) - (df.index[-1] - p_max_idx) - 1
        relative_p_min = len(df) - (df.index[-1] - p_min_idx) - 1

        # Bearish Divergence: 가격은 고점을 높이는데 CVD는 못 높임
        if p_max_idx == df.index[-1] and cvd_recent[-1] < max(cvd_recent[:-1]):
            return {'has_divergence': True, 'type': 'bearish', 'strength': 0.7}
        
        # Bullish Divergence: 가격은 저점을 낮추는데 CVD는 못 낮춤
        if p_min_idx == df.index[-1] and cvd_recent[-1] > min(cvd_recent[:-1]):
            return {'has_divergence': True, 'type': 'bullish', 'strength': 0.7}

        return {'has_divergence': False, 'type': None, 'strength': 0}

    # ─── 청산 클러스터 가격대 추정 ────────────────────────────
    @staticmethod
    def estimate_liquidation_levels(current_price):
        """
        주요 레버리지별 청산 예상 가격을 계산합니다.
        """
        leverage_levels = [10, 25, 50, 100]
        long_liqs = []
        short_liqs = []

        for lev in leverage_levels:
            # 보수적 청산가 계산 (마진 체계 고려)
            long_liq = round(current_price * (1 - 0.9 / lev), 2)
            short_liq = round(current_price * (1 + 0.9 / lev), 2)

            long_liqs.append({'lev': lev, 'price': long_liq})
            short_liqs.append({'lev': lev, 'price': short_liq})

        return {
            'long_liqs': long_liqs,
            'short_liqs': short_liqs,
            'nearest_long': long_liqs[-1]['price'],
            'nearest_short': short_liqs[-1]['price']
        }

    # ─── 종합 스마트 머니 분석 (v3 God-Tier) ──────────────────
    def analyze(self, symbol, data_dict, htf_bias, is_ict_sweep=False):
        """
        스마트 머니 추적 종합 분석.
        10점 만점 시스템으로 환산하기 쉽도록 0~1.0 사이 점수 반환.
        """
        score = 0.0
        reasons = []
        details = {}

        df_15m = data_dict.get('15m')
        current_price = float(df_15m.iloc[-1]['close']) if df_15m is not None else 0

        # ── 1. OI & 세력 의도 분석 (+0.5) ──
        sm_move = self.detect_smart_money_move(symbol, current_price, is_sweep=is_ict_sweep)
        details['sm_move'] = sm_move
        
        if sm_move['score'] > 0:
            score += sm_move['score']
            change_txt = f"{sm_move['change_pct']:+.1f}%"
            if sm_move['intent'] == 'absorption':
                reasons.append(f"💎 세력 흡수(Absorption) 감지: {change_txt} OI 증가 (+0.8)")
            elif sm_move['intent'] == 'accumulation':
                reasons.append(f"💎 세력 포지션 구축: {change_txt} OI 증가 (+0.5)")
        
        # ── 2. CVD 다이버전스 (+0.4) ──
        cvd_div = self.detect_cvd_divergence(df_15m)
        details['cvd_divergence'] = cvd_div
        
        if cvd_div['has_divergence']:
            if (htf_bias == 'bullish' and cvd_div['type'] == 'bullish') or \
               (htf_bias == 'bearish' and cvd_div['type'] == 'bearish'):
                score += 0.4
                reasons.append(f"📊 CVD {cvd_div['type']} 다이버전스 (세력 역매집) (+0.4)")

        # ── 3. 청산 클러스터 인접도 (Bonus +0.1) ──
        liq = self.estimate_liquidation_levels(current_price)
        details['liquidation'] = liq
        
        dist_long = abs(current_price - liq['nearest_long']) / current_price
        dist_short = abs(current_price - liq['nearest_short']) / current_price
        
        if (htf_bias == 'bullish' and dist_long < 0.003) or (htf_bias == 'bearish' and dist_short < 0.003):
            score += 0.1
            target = "하방" if htf_bias == 'bullish' else "상방"
            reasons.append(f"🧲 주요 청산 클러스터 인접 ({target} 유동성 유도) (+0.1)")

        return {
            'score': round(min(1.0, score), 2),
            'reasons': reasons,
            'details': details
        }


if __name__ == "__main__":
    print("─── 아이린 v3: 스마트 머니 추적 엔진 단독 테스트 ───")
    tracker = SmartMoneyTracker()

    # OI 급변
    spike = tracker.detect_oi_spike('BTC/USDT')
    print(f"OI 급변: {spike}")

    # 청산 클러스터
    levels = tracker.estimate_liquidation_levels(71900)
    print(f"\n롱 청산 가격대:")
    for l in levels['long_liquidations']:
        print(f"  {l['leverage']}x → ${l['price']:,.2f} (현재가 대비 -{l['distance_pct']}%)")
    print(f"숏 청산 가격대:")
    for s in levels['short_liquidations']:
        print(f"  {s['leverage']}x → ${s['price']:,.2f} (현재가 대비 +{s['distance_pct']}%)")
