"""
아이린(Irene) v4 — 🤖 Gemini 2.5 Pro 최종 진입 승인 모듈
───────────────────────────────────────────────────────
"모든 데이터를 종합한 후, AI 심판에게 최종 승인을 받는다."

진입 직전 다음 정보를 Gemini에게 전달:
- 현재 가격, EMA 배열, RSI, ATR
- 펀딩비, 공포/탐욕 지수, OI 변화율
- 시장 추세 바이어스 & 진입 방향
→ Gemini가 YES/NO + 이유를 리턴

Gemini API 키가 없으면 → auto_approve 모드로 폴백 (기존 방식 유지)
"""

import os
import time
import json

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class GeminiAdvisor:
    def __init__(self, api_key: str = None, model: str = "gemini-2.5-pro-preview-03-25"):
        """
        Args:
            api_key: Google AI Studio API 키 (없으면 자동 승인 모드)
            model: 사용할 Gemini 모델명
        """
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model_name = model
        self.model = None
        self._enabled = False
        self._call_cache = {}     # 동일 심볼 1분 캐시 (API 과금 절약)
        self._cache_ttl = 60      # 60초

        if not GENAI_AVAILABLE:
            print("⚠️  아이린: google-generativeai 미설치. pip install google-generativeai 필요.")
            return

        if not self.api_key:
            print("⚠️  아이린: GEMINI_API_KEY 없음 → Gemini 검토 비활성화 (자동 승인 모드)")
            return

        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(model_name=self.model_name)
            self._enabled = True
            print(f"✅  아이린: Gemini Advisor 활성화 ({self.model_name})")
        except Exception as e:
            print(f"⚠️  아이린: Gemini 초기화 실패: {e} → 자동 승인 모드")

    # ─── 메인 판단 함수 ──────────────────────────────────────
    def should_enter(self, market_context: dict) -> dict:
        """
        진입 여부를 Gemini에게 판단 받습니다.

        Args:
            market_context: {
                'symbol': str,
                'side': 'buy' | 'sell',
                'entry_price': float,
                'sl': float,
                'tp': float,
                'rsi': float,
                'atr_pct': float,          # ATR / 가격 (%)
                'ema8': float,
                'ema21': float,
                'ema55': float,
                'funding_rate': float,     # 펀딩비 (%)
                'fear_greed': int,         # 0~100
                'oi_change_pct': float,    # OI 변화율 (%)
                'bias': str,               # 'bullish' | 'bearish'
                'confluence_score': float,
                'reasons': list[str],
            }

        Returns:
            dict: {
                'approved': bool,
                'confidence': str,   # 'HIGH' | 'MEDIUM' | 'LOW'
                'reason': str,
                'source': str        # 'gemini' | 'auto'
            }
        """
        # 캐시 확인
        symbol = market_context.get('symbol', '')
        side   = market_context.get('side', '')
        cache_key = f"{symbol}_{side}"
        now = time.time()
        if cache_key in self._call_cache:
            cached = self._call_cache[cache_key]
            if now - cached['ts'] < self._cache_ttl:
                print(f"🤖 Gemini 캐시 재사용: {cache_key}")
                return cached['result']

        if not self._enabled:
            return self._auto_approve(market_context)

        try:
            prompt = self._build_prompt(market_context)
            response = self.model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.2,       # 낮을수록 일관성 있음
                    "max_output_tokens": 300,
                }
            )
            result = self._parse_response(response.text, market_context)
            self._call_cache[cache_key] = {'result': result, 'ts': now}
            return result

        except Exception as e:
            print(f"⚠️  Gemini API 오류: {e} → 자동 승인으로 폴백")
            return self._auto_approve(market_context)

    # ─── 프롬프트 작성 ────────────────────────────────────────
    def _build_prompt(self, ctx: dict) -> str:
        side_kr  = "롱(매수)" if ctx.get('side') == 'buy' else "숏(매도)"
        rr_ratio = round(abs(ctx.get('tp', 0) - ctx.get('entry_price', 1)) /
                         max(abs(ctx.get('entry_price', 1) - ctx.get('sl', 0)), 0.0001), 2)

        ema8  = ctx.get('ema8', 0)
        ema21 = ctx.get('ema21', 0)
        ema55 = ctx.get('ema55', 0)
        ema_order = "정렬됨 ✅" if (ctx.get('side') == 'buy' and ema8 > ema21 > ema55) or \
                                   (ctx.get('side') == 'sell' and ema8 < ema21 < ema55) else "미정렬 ⚠️"

        reasons_text = "\n".join([f"  - {r}" for r in ctx.get('reasons', [])])

        prompt = f"""당신은 전문 암호화폐 선물 트레이더이자 리스크 관리자입니다.
아래 데이터를 분석하여 현재 진입이 합리적인지 판단해주세요.

## 트레이드 요약
- 심볼: {ctx.get('symbol', 'BTC/USDT')}
- 방향: {side_kr}
- 진입가: ${ctx.get('entry_price', 0):,.2f}
- 손절가: ${ctx.get('sl', 0):,.2f}
- 익절가: ${ctx.get('tp', 0):,.2f}
- 손익비 (RR): {rr_ratio}:1

## 기술 지표
- RSI(14): {ctx.get('rsi', 50):.1f}
- ATR 비율: {ctx.get('atr_pct', 0):.2f}% (시장 변동성)
- EMA 정렬 (8/21/55): {ema_order}

## 시장 심리 & 자금 흐름
- 공포/탐욕 지수: {ctx.get('fear_greed', 50)} / 100
- 미결제약정(OI) 변화: {ctx.get('oi_change_pct', 0):+.1f}%
- 펀딩비: {ctx.get('funding_rate', 0):+.4f}%
- HTF 바이어스: {ctx.get('bias', 'neutral')}

## 전략 엔진 판단 이유
컨플루언스 점수: {ctx.get('confluence_score', 0):.1f} / 10.0
{reasons_text}

## 요청
위 데이터를 종합하여:
1. 진입 승인 여부: YES 또는 NO
2. 신뢰도: HIGH / MEDIUM / LOW
3. 핵심 이유 2-3줄

반드시 아래 형식으로만 답하세요:
DECISION: YES (또는 NO)
CONFIDENCE: HIGH (또는 MEDIUM 또는 LOW)
REASON: (이유를 한국어로 2-3줄)
"""
        return prompt

    # ─── 응답 파싱 ────────────────────────────────────────────
    def _parse_response(self, text: str, ctx: dict) -> dict:
        try:
            lines = text.strip().split('\n')
            decision = None
            confidence = 'MEDIUM'
            reason = text.strip()

            for line in lines:
                line = line.strip()
                if line.upper().startswith('DECISION:'):
                    val = line.split(':', 1)[1].strip().upper()
                    decision = 'YES' in val
                elif line.upper().startswith('CONFIDENCE:'):
                    confidence = line.split(':', 1)[1].strip().upper()
                elif line.upper().startswith('REASON:'):
                    reason = line.split(':', 1)[1].strip()

            if decision is None:
                # 파싱 실패 → 텍스트에서 YES/NO 찾기
                decision = 'YES' in text.upper()[:50]

            approved = bool(decision)
            print(f"🤖 Gemini 판단: {'✅ 승인' if approved else '❌ 거부'} ({confidence}) — {reason[:60]}...")

            return {
                'approved': approved,
                'confidence': confidence,
                'reason': reason,
                'source': 'gemini',
                'raw': text.strip()
            }
        except Exception as e:
            print(f"⚠️  Gemini 응답 파싱 실패: {e}")
            return self._auto_approve(ctx)

    # ─── 자동 승인 (Fallback) ─────────────────────────────────
    def _auto_approve(self, ctx: dict) -> dict:
        """Gemini 비활성화 시 기술 지표만으로 자동 판단"""
        score = ctx.get('confluence_score', 0)
        rsi   = ctx.get('rsi', 50)
        side  = ctx.get('side', 'buy')

        # 간단한 규칙 기반 승인
        approved = score >= 5.0
        if side == 'buy'  and rsi > 70: approved = False   # 과매수 롱 차단
        if side == 'sell' and rsi < 30: approved = False   # 과매도 숏 차단

        reason = f"자동 승인 (점수: {score:.1f}/10.0, RSI: {rsi:.0f})"
        print(f"🤖 Auto 판단: {'✅ 승인' if approved else '❌ 거부'} — {reason}")

        return {
            'approved': approved,
            'confidence': 'MEDIUM',
            'reason': reason,
            'source': 'auto'
        }
