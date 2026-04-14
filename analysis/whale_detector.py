"""
아이린(Irene) v3 — 🐙 세력 가격 조종 감지 엔진 (Whale Manipulation Detector)
──────────────────────────────────────────────────────────────
"비정상적 볼륨과 가격 움직임에서 세력의 의도를 간파한다."

탐지 항목 (v3.2: 바이비트 OI 실시간 데이터 추가):
1. 흡수(Absorption) 패턴 — 큰 거래량 but 작은 가격 변동
2. 스톱 헌트(Stop Hunt) — 주요 레벨 돌파 후 즉시 복귀
3. 거래량 이상(Volume Anomaly) — 평균 3배+ 급등
4. 펀더멘털 OI 패턴 — 실제 바이비트 미결제약정 기반 (신규 ✨)

최대 점수: 1.0/10.0 (OI 보너스 추가로 0.5점 상향)
"""

import numpy as np


class WhaleManipulationDetector:
    def __init__(self, fetcher=None):
        """
        Args:
            fetcher: DataFetcher 인스턴스 (바이비트 OI API 연동)
        """
        self.fetcher = fetcher

    # ─── 흡수(Absorption) 패턴 탐지 ──────────────────────────
    @staticmethod
    def detect_absorption(df, lookback=20, vol_threshold=2.0, body_threshold=0.3):
        """
        거래량은 크지만 가격 변동이 작은 "흡수" 패턴을 탐지합니다.
        → 세력이 대량 물량을 시장에 흡수(매집)하거나 분배(매도)하는 중.
        """
        if df is None or len(df) < lookback + 5:
            return []

        patterns = []
        bodies = abs(df['close'] - df['open'])
        avg_body = bodies.rolling(window=lookback).mean()
        avg_vol = df['volume'].rolling(window=lookback).mean()

        for i in range(lookback, len(df)):
            body = bodies.iloc[i]
            vol = df.iloc[i]['volume']
            ab = avg_body.iloc[i]
            av = avg_vol.iloc[i]

            if ab == 0 or av == 0:
                continue

            vol_ratio = vol / av
            body_ratio = body / ab

            if vol_ratio >= vol_threshold and body_ratio <= body_threshold:
                full_range = df.iloc[i]['high'] - df.iloc[i]['low']
                wick_ratio = (full_range - body) / full_range if full_range > 0 else 0

                mid = (df.iloc[i]['high'] + df.iloc[i]['low']) / 2
                direction = 'bullish' if df.iloc[i]['close'] >= mid else 'bearish'

                patterns.append({
                    'index': i,
                    'type': f'{direction}_absorption',
                    'vol_ratio': round(vol_ratio, 2),
                    'body_ratio': round(body_ratio, 2),
                    'wick_ratio': round(wick_ratio, 2),
                    'timestamp': df.iloc[i]['timestamp'] if 'timestamp' in df.columns else i
                })

        return patterns

    # ─── 스톱 헌트(Stop Hunt) 탐지 ───────────────────────────
    @staticmethod
    def detect_stop_hunt(df, lookback=20, wick_pct=0.003):
        """
        주요 수평 레벨(최근 고/저점)을 꼬리로만 돌파하고
        즉시 복귀하는 "스톱 헌트" 패턴을 탐지합니다.
        """
        if df is None or len(df) < lookback + 5:
            return []

        hunts = []

        for i in range(lookback, len(df)):
            window = df.iloc[i - lookback:i]
            recent_high = window['high'].max()
            recent_low = window['low'].min()
            candle = df.iloc[i]

            if candle['high'] > recent_high:
                wick_above = candle['high'] - max(candle['open'], candle['close'])
                full_range = candle['high'] - candle['low']

                if full_range > 0 and wick_above / full_range > 0.5 and candle['close'] < recent_high:
                    hunts.append({
                        'index': i,
                        'type': 'bearish_stop_hunt',
                        'level': round(recent_high, 4),
                        'wick_size_pct': round(wick_above / candle['close'] * 100, 3),
                        'timestamp': candle['timestamp'] if 'timestamp' in df.columns else i
                    })

            if candle['low'] < recent_low:
                wick_below = min(candle['open'], candle['close']) - candle['low']
                full_range = candle['high'] - candle['low']

                if full_range > 0 and wick_below / full_range > 0.5 and candle['close'] > recent_low:
                    hunts.append({
                        'index': i,
                        'type': 'bullish_stop_hunt',
                        'level': round(recent_low, 4),
                        'wick_size_pct': round(wick_below / candle['close'] * 100, 3),
                        'timestamp': candle['timestamp'] if 'timestamp' in df.columns else i
                    })

        return hunts

    # ─── 거래량 이상 탐지 ────────────────────────────────────
    @staticmethod
    def detect_volume_anomaly(df, lookback=20, threshold=3.0):
        """평균 대비 threshold배 이상의 거래량 급등을 탐지합니다."""
        if df is None or len(df) < lookback + 3:
            return []

        anomalies = []
        avg_vol = df['volume'].rolling(window=lookback).mean()

        for i in range(lookback, len(df)):
            vol = df.iloc[i]['volume']
            av = avg_vol.iloc[i]
            if av == 0:
                continue

            ratio = vol / av
            if ratio >= threshold:
                candle = df.iloc[i]
                direction = 'bullish' if candle['close'] > candle['open'] else 'bearish'
                anomalies.append({
                    'index': i,
                    'type': f'{direction}_volume_spike',
                    'vol_ratio': round(ratio, 2),
                    'volume': vol,
                    'direction': direction,
                    'timestamp': candle['timestamp'] if 'timestamp' in df.columns else i
                })

        return anomalies

    # ─── OI 기반 포지션 분석 (신규 ✨) ──────────────────────
    def analyze_oi(self, symbol, htf_bias, oi_data=None, ls_data=None):
        """
        미결제약정(OI) + 롱/숏 비율을 조합하여 세력 포지션 방향을 추정합니다.

        OI 해석 로직:
        - OI 상승 + bullish 바이어스 → 롱 세력 집결 확인
        - OI 상승 + bearish 바이어스 → 숨 세력 집결 확인
        - OI 급락               → 포지션 대량 청산 → 방향 전환 위험
        - 롱 과밀 + bearish      → 숏스 스퀴즈 가능성 확인

        Returns:
            dict: {'score': float, 'reasons': list, 'oi_info': dict}
        """
        score = 0.0
        reasons = []
        oi_info = {}

        # OI 데이터 가져오기 (실제 또는 mock)
        if oi_data is None and self.fetcher:
            oi_data = self.fetcher.fetch_oi_change_rate(symbol)
        if ls_data is None and self.fetcher:
            ls_data = self.fetcher.fetch_long_short_history(symbol)

        if not oi_data:
            return {'score': 0, 'reasons': ['🐙 OI 데이터 없음'], 'oi_info': {}}

        oi_trend = oi_data.get('trend', 'neutral')
        oi_chg   = oi_data.get('oi_change_pct', 0)
        oi_info['oi_change_pct'] = oi_chg
        oi_info['oi_trend']      = oi_trend

        # ── 1. OI 추세 + 바이어스 일치 (+0.35) ──
        if oi_trend == 'rising':
            if htf_bias in ('bullish', 'bearish'):
                score += 0.35
                dir_text = '롱' if htf_bias == 'bullish' else '숏'
                reasons.append(f"🐙 OI 상승({oi_chg:+.1f}%) + {htf_bias} 바이어스 → {dir_text} 세력 집결 확인 (+0.35)")
        elif oi_trend == 'falling':
            reasons.append(f"⚠️ OI 감소({oi_chg:+.1f}%) → 포지션 청산 진행 중, 방향전환 주의")
            oi_info['reversal_risk'] = True
        else:
            reasons.append(f"🐙 OI 중립({oi_chg:+.1f}%) → 모멘텀 부족")

        # ── 2. 롱숏 비율 역발상 (+0.15) ──
        if ls_data:
            ls_bias  = ls_data.get('bias', 'neutral')
            ls_ratio = ls_data.get('current_ratio', 1.0)
            oi_info['ls_ratio'] = ls_ratio
            oi_info['ls_bias']  = ls_bias

            if htf_bias == 'bearish' and ls_bias == 'long_heavy':
                score += 0.15
                reasons.append(f"🐙 롱비율 {ls_ratio:.2f} (롱 과밀) + 숏 바이어스 → 숏스 스퀴즈 가능성 (+0.15)")
            elif htf_bias == 'bullish' and ls_bias == 'short_heavy':
                score += 0.15
                reasons.append(f"🐙 롱비율 {ls_ratio:.2f} (숏 과밀) + 롱 바이어스 → 롱 스퀴즈 가능성 (+0.15)")

        oi_info['oi_score'] = round(score, 2)
        return {'score': round(score, 2), 'reasons': reasons, 'oi_info': oi_info}

    # ─── 종합 세력 조종 분석 ─────────────────────────────────
    def analyze(self, data_dict, htf_bias, symbol=None, oi_data=None, ls_data=None):
        """
        OHLCV 데이터에서 세력의 가격 조종 패턴을 탐지합니다.
        v3.2: 실시간 OI 데이터 통합으로 세력 포지션 방향 확인 추가

        Args:
            data_dict: {'15m': df, '5m': df, ...}
            htf_bias: 'bullish' 또는 'bearish'
            symbol: 심볼 (실전 모드 OI 호출용)
            oi_data: OI 변화율 dict (백테스트/mock 시 주입 가능)
            ls_data: L/S 비율 dict

        Returns:
            dict: {'score': float(0~1.0), 'reasons': [...], 'details': {}}
        """
        score = 0.0
        reasons = []
        details = {}

        df = data_dict.get('15m')
        if df is None or len(df) < 30:
            reasons.append("🐙 세력 감지 데이터 부족")
            return {'score': 0, 'reasons': reasons, 'details': {}}

        # ── 1. 흡수 패턴 (+0.2) ──
        absorptions = self.detect_absorption(df)
        recent_abs = [a for a in absorptions if a['index'] >= len(df) - 5]
        details['absorption_count'] = len(recent_abs)

        if recent_abs:
            latest = recent_abs[-1]
            if (htf_bias == 'bullish' and 'bullish' in latest['type']) or \
               (htf_bias == 'bearish' and 'bearish' in latest['type']):
                score += 0.2
                reasons.append(
                    f"🐙 {latest['type']} 감지 (거래량 {latest['vol_ratio']}x, "
                    f"꼬리 비율 {latest['wick_ratio']:.0%}) — 세력 매집 중 (+0.2)")
            else:
                reasons.append(f"🐙 {latest['type']} 감지 — 바이어스 역방향 (경고)")
        else:
            reasons.append("🐙 흡수 패턴 미감지")

        # ── 2. 스톱 헌트 후 반전 (+0.2) ──
        stop_hunts = self.detect_stop_hunt(df)
        recent_hunts = [h for h in stop_hunts if h['index'] >= len(df) - 5]
        details['stop_hunt_count'] = len(recent_hunts)

        if recent_hunts:
            latest_hunt = recent_hunts[-1]
            if (htf_bias == 'bullish' and 'bullish' in latest_hunt['type']) or \
               (htf_bias == 'bearish' and 'bearish' in latest_hunt['type']):
                score += 0.2
                reasons.append(
                    f"🎣 {latest_hunt['type']} 포착 (레벨: ${latest_hunt['level']:,.2f}, "
                    f"꼬리 {latest_hunt['wick_size_pct']:.2f}%) — 세력 유동성 사냥 후 반전 (+0.2)")
            else:
                reasons.append(f"🎣 {latest_hunt['type']} 감지 — 바이어스 역방향")
        else:
            reasons.append("🎣 스톱 헌트 미감지")

        # 거래량 이상 (참고 정보)
        vol_anomalies = self.detect_volume_anomaly(df)
        recent_anom = [a for a in vol_anomalies if a['index'] >= len(df) - 3]
        if recent_anom:
            latest_anom = recent_anom[-1]
            reasons.append(
                f"📢 거래량 이상 감지: {latest_anom['vol_ratio']}x ({latest_anom['direction']}) — 참고")
        details['volume_anomaly_count'] = len(recent_anom)

        # ── 3. OI 기반 세력 포지션 분석 (+0.5) ──
        if symbol or oi_data:
            oi_result = self.analyze_oi(symbol or '', htf_bias, oi_data=oi_data, ls_data=ls_data)
            oi_score = min(0.5, oi_result['score'])
            score += oi_score
            for r in oi_result['reasons']:
                reasons.append(r)
            details['oi_info'] = oi_result.get('oi_info', {})

        return {
            'score': round(min(1.0, score), 2),  # 최대 1.0점
            'reasons': reasons,
            'details': details
        }


if __name__ == "__main__":
    print("─── 아이린 v3.2: 세력 가격 조종 감지 엔진 단독 테스트 ───")
    detector = WhaleManipulationDetector()
    print("초기화 완료. 실제 데이터 연동 필요.")
