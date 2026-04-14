"""
아이린(Irene) v3 — 🧠 군중 심리 역이용 엔진 (Crowd Psychology Engine)
──────────────────────────────────────────────────────────────
"개미가 몰리는 곳의 반대편에 세력이 있다."

데이터 소스 (전부 무료, 키 불필요):
1. Bybit V5 API — 롱/숏 비율 (/v5/market/account-ratio)
2. Bybit V5 API — 펀딩비 (ccxt)
3. Alternative.me — Fear & Greed Index

최대 점수: 1.5/10.0
"""

import requests
import time


class CrowdPsychologyEngine:
    def __init__(self, fetcher=None):
        """
        Args:
            fetcher: DataFetcher 인스턴스 (Bybit API 재활용)
        """
        self.fetcher = fetcher
        self._fg_cache = {'value': None, 'ts': 0}   # Fear & Greed 캐시 (5분)
        self._ls_cache = {}                           # 심볼별 롱/숏 비율 캐시

    # ─── Fear & Greed Index ───────────────────────────────
    def fetch_fear_greed_index(self):
        """
        Alternative.me에서 공포/탐욕 지수를 가져옵니다.
        0 = Extreme Fear, 100 = Extreme Greed
        5분 캐시 적용.
        """
        now = time.time()
        if self._fg_cache['value'] is not None and (now - self._fg_cache['ts']) < 300:
            return self._fg_cache['value']

        try:
            resp = requests.get('https://api.alternative.me/fng/?limit=1', timeout=10)
            data = resp.json()
            value = int(data['data'][0]['value'])
            classification = data['data'][0]['value_classification']
            self._fg_cache = {'value': value, 'classification': classification, 'ts': now}
            print(f"아이린: Fear & Greed Index = {value} ({classification})")
            return value
        except Exception as e:
            print(f"아이린: Fear & Greed 지수 조회 실패: {e}")
            return 50  # 기본값: 중립

    def get_fear_greed_classification(self):
        """캐시된 분류명 반환"""
        return self._fg_cache.get('classification', 'Neutral')

    # ─── Bybit 롱/숏 비율 (DataFetcher 통합) ───────────────
    def fetch_long_short_ratio(self, symbol, period='1h'):
        """
        DataFetcher를 통해 롱/숏 비율을 가져옵니다.
        """
        if self.fetcher:
            return self.fetcher.fetch_long_short_ratio(symbol, period)
        return 1.0

    # ─── 펀딩비 조회 (DataFetcher 사용) ─────────────────────
    def fetch_funding_rate(self, symbol):
        """
        ccxt를 통해 현재 펀딩비를 가져옵니다.
        """
        if self.fetcher:
            rate = self.fetcher.fetch_funding_rate(symbol)
            return rate if rate is not None else 0.0
        return 0.0

    # ─── 종합 군중 심리 분석 (v3 God-Tier) ────────────────────
    def analyze(self, symbol, htf_bias):
        """
        모든 군중 심리 지표를 종합하여 점수(0~1.0)를 산출합니다.
        """
        score = 0.0
        reasons = []
        details = {}

        # ── 1. 롱/숏 비율 분석 (주요 필터) ──
        ls_ratio = self.fetch_long_short_ratio(symbol)
        details['ls_ratio'] = round(ls_ratio, 3)

        if htf_bias == 'bearish' and ls_ratio >= 1.5:
            # 숏 타겟인데 개미가 롱에 몰림 → 역발상 성공 확률 급상승
            bonus = 0.5 if ls_ratio >= 2.0 else 0.3
            score += bonus
            reasons.append(f"🧠 롱/숏 비율 {ls_ratio:.2f} (롱 과밀) — 개미 반대 방향 진입 유리 (+{bonus})")
        elif htf_bias == 'bullish' and ls_ratio <= 0.67:
            # 롱 타겟인데 개미가 숏에 몰림
            bonus = 0.5 if ls_ratio <= 0.5 else 0.3
            score += bonus
            reasons.append(f"🧠 롱/숏 비율 {ls_ratio:.2f} (숏 과밀) — 개미 반대 방향 진입 유리 (+{bonus})")

        # ── 2. 펀딩비 분석 (+0.3) ──
        funding = self.fetch_funding_rate(symbol)
        details['funding_rate'] = round(funding, 6)

        # 펀딩비가 바이어스 반대방향으로 과열되었는지 확인 (예: 롱 타겟인데 펀딩비는 마이너스 = 숏 과열)
        if htf_bias == 'bullish' and funding < -0.0002:
            score += 0.3
            reasons.append(f"💸 펀딩비 {funding:.4%} (숏 과열) — 숏 스퀴즈 기대 가능 (+0.3)")
        elif htf_bias == 'bearish' and funding > 0.0002:
            score += 0.3
            reasons.append(f"💸 펀딩비 {funding:.4%} (롱 과열) — 롱 스퀴즈 기대 가능 (+0.3)")

        # ── 3. Fear & Greed 지수 분석 (+0.2) ──
        fg_value = self.fetch_fear_greed_index()
        fg_class = self.get_fear_greed_classification()
        details['fear_greed'] = fg_value

        if (htf_bias == 'bullish' and fg_value <= 25) or (htf_bias == 'bearish' and fg_value >= 75):
            score += 0.2
            reasons.append(f"😱 시장 심리 {fg_class}({fg_value}) — 극단적 구간 역발상 (+0.2)")

        return {
            'score': round(min(1.0, score), 2),
            'reasons': reasons,
            'details': details
        }


if __name__ == "__main__":
    print("─── 아이린 v3: 군중 심리 엔진 단독 테스트 ───")
    engine = CrowdPsychologyEngine()

    # Fear & Greed
    fg = engine.fetch_fear_greed_index()
    print(f"Fear & Greed: {fg} ({engine.get_fear_greed_classification()})")

    # 롱숏 비율 (BTC)
    ls = engine.fetch_long_short_ratio('BTC/USDT')
    print(f"BTC 롱/숏 비율: {ls:.3f}")

    # 종합 분석
    result = engine.analyze('BTC/USDT', 'bullish')
    print(f"\n점수: {result['score']}/1.5")
    for r in result['reasons']:
        print(f"  {r}")
