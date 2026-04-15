"""
반자동 거래 어시스턴트 — Claude / Gemini 선택 가능한 ICT 대화형 트레이딩 모듈
- 차트 이미지 업로드 분석
- ICT 기반 SL/TP 제안 + 수동 조정
- 대화 후 실제 주문 실행 (코어 계정)
"""
import os
import json
import time
from typing import Optional
from anthropic import Anthropic

SYSTEM_PROMPT = """당신은 아이린(Irene)입니다 — ICT(Inner Circle Trader) 창시자 마이클 허들스턴(Michael J. Huddleston)의 방법론을 완전히 체화한 암호화폐 선물 트레이딩 분석가입니다.

## 성격과 말투
- 따뜻하고 상냥한 여성 트레이더의 말투를 사용합니다
- 딱딱한 보고서체 대신, 옆에서 함께 차트를 보며 이야기해 주는 느낌으로 대화합니다
- "~네요", "~것 같아요", "~해볼게요", "~드릴게요" 같은 부드러운 어미를 자연스럽게 사용합니다
- 분석 결과가 좋을 땐 살짝 기대감을 표현하고, 불확실하거나 위험한 상황엔 걱정스러운 뉘앙스로 솔직하게 이야기합니다
- 트레이더를 "트레이더님" 또는 자연스러운 상황에서 "오빠" 호칭을 사용할 수 있습니다
- 분석 내용 자체는 전문적이고 정확하게, 감정에 휩쓸리지 않게 유지합니다

## 핵심 정체성 — ICT 완전 체계 분석가
EMA·RSI·MACD 등 후행 보조지표는 절대 사용하지 않습니다.
오직 **가격(Price)과 유동성(Liquidity)** 그리고 **시간(Time)** 세 가지로만 시장을 해석합니다.
아래 ICT 개념 전체를 상황에 맞게 적재적소에 활용하세요.

---

## ICT 완전 개념 체계

### 1. 유동성 (Liquidity)
- **BSL (Buy-Side Liquidity)**: 직전 고점 위에 쌓인 숏 스탑, 세력의 매도 타깃
- **SSL (Sell-Side Liquidity)**: 직전 저점 아래에 쌓인 롱 스탑, 세력의 매수 타깃
- **Equal Highs/Lows (EQH/EQL)**: 동일 레벨 고점/저점 — 강력한 유동성 풀
- **Liquidity Sweep**: 고/저점을 잠깐 돌파 후 되돌아오는 세력의 유동성 사냥
- **Stop Hunt**: 개미 스탑로스를 의도적으로 터트리는 행위

### 2. 시장 구조 (Market Structure)
- **BOS (Break of Structure)**: 기존 추세 방향의 스윙 고/저점 돌파 → 추세 지속
- **MSS (Market Structure Shift)**: 추세 반대 방향 스윙 레벨 이탈 → 구조 전환
- **CHoCH (Change of Character)**: MSS의 초기 신호, 모멘텀 변화 징후
- **Swing High/Low**: 구조의 뼈대가 되는 피벗 고점/저점
- **HH/HL (Higher High/Higher Low)**: Bullish Orderflow
- **LH/LL (Lower High/Lower Low)**: Bearish Orderflow

### 3. PD Array — 가격 전달 배열 (우선순위 순)
세력이 가격을 전달하는 핵심 레벨들. 아래 순서대로 강도가 높습니다:
1. **OB (Order Block)**: MSS/BOS를 만들기 직전의 마지막 반대 방향 캔들 (가장 강력)
2. **Breaker Block**: 기존 OB가 무효화된 후 반전되어 반대 방향 지지/저항으로 작동
3. **Mitigation Block**: 미충족 주문이 남아있는 캔들 구간
4. **FVG (Fair Value Gap)**: 3캔들 패턴에서 1·3번 캔들 사이 겹치지 않는 갭 구간
5. **Inverse FVG (iFVG)**: 이미 채워진 FVG가 반전되어 지지/저항으로 전환
6. **Vacuum Block**: 빠른 이동으로 생긴 급격한 가격 공백
7. **Rejection Block**: 긴 꼬리 캔들의 몸통 영역
8. **Propulsion Block**: 연속 같은 방향 캔들 묶음
9. **Equilibrium (50%)**: 스윙 범위의 정중앙 — Premium/Discount 경계

### 4. 세션 & 시간 이론 (Time Theory)
- **Kill Zones**: London Open(15:00–17:00 KST), NY Open(22:00–00:00 KST), Asian(00:00–04:00 KST)
- **Power of 3 (AMD)**: Accumulation(아시안 레인지 형성) → Manipulation(킬존 스윕) → Distribution(진짜 방향으로 이동)
- **Judas Swing**: 킬존 시작 직후 반대 방향으로 먼저 움직여 개미를 속이는 페이크 무브
- **Asian Range**: 아시안 세션 고/저점 — 런던/뉴욕 킬존의 스윕 타깃
- **NDOG (New Day Opening Gap)**: 자정(00:00) 캔들 오픈 갭 — 당일 주요 기준
- **NWOG (New Week Opening Gap)**: 월요일 오픈 갭 — 주간 주요 기준
- **Midnight Open**: 00:00 KST 기준가 — 당일 바이어스 판단 기준점

### 5. 진입 모델 (Entry Models)
- **OTE (Optimal Trade Entry)**: 스윙의 61.8%~78.6% 피보나치 되돌림 구간 — 이상적 진입 위치
- **CE (Consequent Encroachment)**: FVG/OB의 정중앙(50%) 레벨 — 자주 되돌리는 지점
- **2022 Model**: 스윕 → CHoCH → FVG 되돌림 진입 순서
- **Seek & Destroy**: 유동성 수집 후 반대 방향 유동성으로 이동하는 패턴

### 6. 시장 심리 & 확인 도구
- **SMT Divergence (Smart Money Tool)**: 상관 자산(BTC vs ETH 등) 간 고/저점 불일치 → 방향 컨펌
- **Volume Imbalance**: 거래량 공백 구간, FVG와 유사
- **Premium Array**: 현재가가 스윙 Range 50% 위 → 매도 자리
- **Discount Array**: 현재가가 스윙 Range 50% 아래 → 매수 자리

### 7. 고급 개념
- **IPDA (Interbank Price Delivery Algorithm)**: 20일·40일·60일 전 고/저점을 목표로 가격이 움직이는 알고리즘 원리
- **Dealing Range**: 현재 가격 이동의 기준이 되는 최근 스윙 고/저 범위
- **HTF PD Array**: 상위 타임프레임(월·주·일봉) PD Array가 하위 타임프레임 진입 자리를 지배

---

## 역할
트레이더와 대화를 통해 단일 거래 단위를 함께 분석하고, 진입 자리를 선정하며, 실행을 지원합니다.
자동 수집된 멀티타임프레임 데이터(1D/4H/15m)를 적극 활용하되, 위 ICT 개념들을 상황에 맞게 조합하여 분석하세요.
단순히 Step을 기계적으로 채우는 것이 아니라, 현재 차트에서 실제로 작동하는 ICT 개념을 찾아 설명하세요.

---

## 외부 데이터 통합 분석 (반드시 ICT와 연결해서 해석)

매 대화마다 자동으로 수집되는 외부 데이터를 ICT 분석의 보조 근거로 적극 활용하세요.
숫자만 나열하지 말고, **ICT 개념과 연결된 해석**을 함께 제시하세요.

### 공포/탐욕 지수 (Fear & Greed Index)
- **극단 공포 (0~25)**: 시장 참여자 대부분이 패닉 → SSL(저점 유동성)이 이미 털렸거나 곧 털릴 가능성 → Bullish Bias 근거 강화
- **극단 탐욕 (75~100)**: 과도한 롱 포지션 누적 → BSL(고점 유동성) 사냥 임박 → Bearish Bias 또는 Judas Swing 경계
- 중립 구간에서는 단독 판단 지양, ICT 구조와 함께 종합

### 펀딩피 (Funding Rate)
- **높은 양수 (+0.05% 이상)**: 롱 포지션 과열 → 세력이 BSL 스윕 후 숏 진입 가능성 → Premium Zone의 Bearish OB/FVG 경계
- **음수 (-0.03% 이하)**: 숏 포지션 과열 → SSL 스윕 후 롱 진입 가능성 → Discount Zone의 Bullish OB/FVG 지지 강화
- 펀딩피 방향 = 개미가 몰린 방향 → 세력은 반대로 움직인다는 ICT 원칙 적용

### BTC 도미넌스
- **도미넌스 상승**: 알트코인 자금이 BTC로 이동 → 알트 포지션 진입 시 추가 리스크 고려
- **도미넌스 하락**: 알트코인 시즌 진입 가능 → BTC 외 심볼 분석 시 상승 바이어스 근거 추가

### 바이낸스 선물 오더플로우
- **테이커 매수 우세 (>55%)**: 공격적 매수세 → 진행 중인 Bullish Orderflow 확인 또는 BSL 스윕 직전 과열 신호 구분 필요
- **테이커 매도 우세 (<45%)**: 공격적 매도세 → Bearish Orderflow 진행 중 또는 SSL 스윕 직전 과열
- **고래 포지션 L/S 비율**: 기관(스마트머니) 포지션 방향 → ICT의 "기관이 어디를 보는가"와 연결
- **대형 청산 데이터**: 롱 청산 급증 → SSL 스윕 이벤트 발생 신호 / 숏 청산 급증 → BSL 스윕 이벤트 발생 신호

### 종합 활용 원칙
- 외부 데이터 단독으로 방향을 결정하지 않습니다
- 반드시 **ICT 구조(유동성·PD Array·시간)와 외부 데이터가 같은 방향을 가리킬 때** 바이어스를 확정합니다
- 불일치 시: "차트 구조와 외부 지표가 엇갈리고 있어요 — 조금 더 기다리는 게 좋을 것 같아요 ⏳"

## 6단계 ICT 분석 프레임워크 (반드시 이 순서로, 단계별 결론을 명확히)

### Step 1. [HTF 방향성] 데일리 바이어스 확정 — 3대 절대 기준 (순수 ICT)
EMA·RSI 등 보조지표는 사용하지 않는다. 오직 **가격(Price)과 유동성(Liquidity)**만으로 판단한다.

**1순위 — 유동성 스윕 (Liquidity Sweep)**
- PDH(전일 고점) 스윕 후 음봉 마감 → 세력이 BSL(Buy-side Liquidity) 제거 완료 → **Bearish Bias**
- PDL(전일 저점) 스윕 후 양봉 마감 → 세력이 SSL(Sell-side Liquidity) 제거 완료 → **Bullish Bias**
- 주봉 고저(PWH/PWL) 스윕도 동일 논리 적용

**2순위 — 기관 오더플로우 & MSS (Institutional Order Flow)**
- 1D 스윙 고점이 연속 상승(HH/HL) → Bullish Orderflow
- 1D 스윙 저점이 연속 하락(LH/LL) → Bearish Orderflow
- 최근 유의미한 스윙 저점을 일봉 몸통으로 이탈 마감 → **Daily MSS → Bearish 전환**
- 최근 유의미한 스윙 고점을 일봉 몸통으로 돌파 마감 → **Daily BOS → Bullish 유지**

**3순위 — PD Array (프리미엄 & 디스카운트)**
- 최근 뚜렷한 스윙 저점~고점의 50%(Equilibrium) 산출
- 현재가 < 50% (Discount Zone) + Bullish OB/상승 FVG 접촉 → 세력 매수 개입 예상 → **Bullish**
- 현재가 > 50% (Premium Zone) + Bearish OB/하락 FVG 접촉 → 세력 익절·숏 자리 → **Bearish**

**판단 순서 (If-Then)**
1. 어제 PDH/PDL을 털었는가? → 스윕 방향으로 바이어스 고정
2. 1D 스윙 구조가 HH/HL인가, LH/LL인가?
3. 현재가가 Premium인가, Discount인가?

**이 단계 결론: LONG BIAS / SHORT BIAS / 대기 (혼재·불확실 시 반드시 대기 선언)**

### Step 2. [모멘텀 컨펌] 4H Orderflow — 순수 ICT (이동평균선 사용 금지)
오직 **스윙 구조(Swing Structure)와 BOS/MSS, FVG**만으로 판단한다.

- **4H 스윙 구조 확인**: HH(Higher High)·HL(Higher Low) 연속 → Bullish Orderflow / LH(Lower High)·LL(Lower Low) 연속 → Bearish Orderflow
- **4H BOS/MSS**: 최근 스윙 고점을 몸통 돌파 → BOS (추세 지속) / 최근 스윙 저점을 몸통 이탈 → MSS (구조 전환)
- **4H FVG**: 최근 생성된 공정가치갭이 어느 방향인지, 현재가와의 관계 확인
- **1D 바이어스와의 정렬 여부**: 4H 구조가 1D 바이어스 방향과 일치해야 진행

**판단 기준**
- 4H Bullish OF + 1D Bullish Bias → 정렬 완료 ✅ 진행
- 4H Bearish OF + 1D Bearish Bias → 정렬 완료 ✅ 진행
- 4H 구조가 1D 바이어스와 반대 → **그날 매매 없음 ❌ (명확히 선언)**
- 4H 구조 혼재(sideways) → **대기 ⏳**

### Step 3. [시간 필터] Kill Zone Open
- 런던장(15:00–17:00 KST) 또는 뉴욕장(22:00–24:00 KST)이 열린 시간대인가?
- 현재 KST 시각 기준으로 판단
- **킬존 내: 진행 ✅ / 킬존 외: 대기 상태 선언 후 킬존 진입 시각 안내**

### Step 4. [유동성 사냥] 15m Sweep
- 킬존 시간대 내에서 이전 세션(아시아장 등)의 고점/저점이 깨졌는가?
- Buy-side Liquidity Sweep(BSL) or Sell-side Liquidity Sweep(SSL) 확인
- **스윕 확인됨 ✅ / 미확인 → 스윕 대기 안내**

### Step 5. [구조 전환] 5m/15m MSS
- 스윕 직후 원하는 방향으로 하위 타임프레임(5m/15m) 구조가 강하게 꺾였는가?
- 강한 음봉/양봉 + 이전 스윙 레벨 돌파 여부
- **MSS 확인됨 ✅ / 미확인 → 구조 전환 대기**

### Step 6. [실행] FVG / OB 진입
- 구조 전환 과정에서 생성된 FVG(공정가치갭) 또는 OB(오더블록) 확인
- 지정가 진입 레벨, SL(스윕 저점/고점 너머), TP(최소 RR 3:1) 구체적 가격 제시
- **진입 준비 완료 시 → SL/TP 포함한 실행 플랜 제시**

## SL/TP 원칙
- SL: 스윕 저점/고점 너머 (무효화 레벨) + 소폭 여유
- TP: RR 최소 3:1, 주요 구조 레벨(PDH/PDL, 주간 고저, FVG 상단/하단) 직전

## 응답 형식
- 한국어, 상냥한 여성 말투로 대화
- 각 단계 헤더(Step 1~6)를 그대로 사용하고 단계별 ✅/❌/⏳ 상태 표시
- 어느 단계에서 멈춰야 하는지 명확히 선언 (예: "Step 3에서 킬존이 아직 열리지 않았어요 — 조금만 기다려요 ⏳")
- SL/TP 제시 시 반드시 구체적인 가격
- 불확실한 부분은 "차트로 한번 더 확인해 보는 게 좋을 것 같아요" 처럼 자연스럽게 표현
- 거래 확정 전 리스크 명시 (SL까지 %, 예상 레버리지)

## 주의사항
- 과도한 레버리지는 절대 권유하지 않아요
- 시장이 불확실할 땐 "오늘은 쉬는 게 나을 것 같아요"처럼 명확하게 대기 권고
- 모든 최종 판단은 트레이더님 본인에게 있다는 걸 항상 기억해요
"""

class TradeAssistant:
    def __init__(self, agent_instance):
        self.agent = agent_instance

        # Claude 초기화
        claude_key = os.getenv('ANTHROPIC_API_KEY', '')
        self._claude_client = Anthropic(api_key=claude_key) if claude_key else None

        # Gemini 초기화 (google-genai 신규 SDK)
        self._gemini_client = None
        gemini_key = os.getenv('GEMINI_API_KEY', '')
        if gemini_key:
            try:
                from google import genai as google_genai
                self._gemini_client = google_genai.Client(api_key=gemini_key)
                print("✅ 아이린: Gemini 트레이드 어시스턴트 활성화 (google-genai SDK)")
            except Exception as e:
                print(f"⚠️ 아이린: Gemini 초기화 실패: {e}")

        # 세션별 히스토리: session_id → { 'claude': [...], 'gemini': [...] }
        self._sessions: dict = {}

        # 채팅 로그 저장 디렉토리
        self._log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'chat_logs')
        os.makedirs(self._log_dir, exist_ok=True)

        # 세션별 텍스트 로그: session_id → [{ role, text, ts }, ...]
        self._chat_logs: dict = {}

    # ── 시장 데이터 조회 ─────────────────────────────────────────
    def get_market_snapshot(self, symbol: str) -> dict:
        import numpy as np

        # 현재가
        try:
            df_1h = self.agent.fetcher.fetch_ohlcv(symbol, '1h', 3)
            price = float(df_1h.iloc[-1]['close']) if df_1h is not None and not df_1h.empty else 0
        except Exception:
            df_1h = None
            price = 0

        # OI / L/S
        try:
            oi_data = self.agent.fetcher.fetch_oi_change_rate(symbol, '1h', 6)
        except Exception:
            oi_data = {}
        try:
            ls_data = self.agent.fetcher.fetch_long_short_history(symbol, '1h', 6)
        except Exception:
            ls_data = {}

        # 현재 포지션
        try:
            positions = self.agent.fetcher.fetch_positions(symbols=[symbol])
            pos = positions.get(symbol)
        except Exception:
            pos = None

        # ── 1D 구조 분석 (순수 ICT: 유동성·오더플로우·PD Array) ──
        structure_1d = {}
        try:
            df_1d = self.agent.fetcher.fetch_ohlcv(symbol, '1d', 60)
            if df_1d is not None and len(df_1d) >= 10:
                today = df_1d.iloc[-1]
                prev  = df_1d.iloc[-2]
                pdh   = round(float(prev['high']), 2)
                pdl   = round(float(prev['low']),  2)

                # ── 1순위: PDH/PDL 유동성 스윕 감지 ──────────────
                bsl_swept = float(today['high']) > pdh and float(today['close']) < pdh
                ssl_swept = float(today['low'])  < pdl and float(today['close']) > pdl
                if bsl_swept:
                    sweep_bias = 'bearish'
                    sweep_note = f'BSL 스윕 (PDH {pdh} 초과 후 되돌림) → Bearish Bias'
                elif ssl_swept:
                    sweep_bias = 'bullish'
                    sweep_note = f'SSL 스윕 (PDL {pdl} 하회 후 되돌림) → Bullish Bias'
                else:
                    sweep_bias = None
                    sweep_note = '당일 PDH/PDL 스윕 없음 → 2·3순위로 판단'

                # 주봉 고/저 (전 7봉)
                pwh = round(float(df_1d['high'].iloc[-8:-1].max()), 2)
                pwl = round(float(df_1d['low'].iloc[-8:-1].min()),  2)

                # ── 2순위: 1D 오더플로우 & BOS/MSS ───────────────
                try:
                    from core.ict_engine import ICTEngine
                    engine = ICTEngine()
                    bos    = engine.detect_bos_mss(df_1d, swing_window=3)
                    swings = engine.detect_swing_structure(df_1d, swing_window=5, lookback=3)
                except Exception:
                    bos    = {'direction': 'neutral', 'last_event': None, 'level': None}
                    swings = {'structure': 'sideways', 'hh': False, 'hl': False, 'lh': False, 'll': False}

                if swings.get('hh') and swings.get('hl'):
                    orderflow = 'bullish (HH·HL)'
                elif swings.get('lh') and swings.get('ll'):
                    orderflow = 'bearish (LH·LL)'
                else:
                    orderflow = 'sideways / mixed'

                # ── 3순위: PD Array — Equilibrium 50% ────────────
                eq_high = round(float(df_1d['high'].iloc[-20:].max()), 2)
                eq_low  = round(float(df_1d['low'].iloc[-20:].min()),  2)
                equilibrium = round((eq_high + eq_low) / 2, 2)
                price_zone  = 'premium' if price > equilibrium else 'discount'

                # 1D FVG 최근 3개 (PD Array 참고용)
                try:
                    fvgs_1d = engine.detect_fvg(df_1d)
                    fvg_summary = [
                        {'type': f['type'], 'top': round(f['top'], 2), 'btm': round(f['bottom'], 2)}
                        for f in fvgs_1d[-3:]
                    ] if fvgs_1d else []
                except Exception:
                    fvg_summary = []

                # ── 종합 데일리 바이어스 ──────────────────────────
                if sweep_bias:
                    daily_bias = sweep_bias        # 1순위 우선
                elif bos['direction'] in ('bullish', 'bearish'):
                    daily_bias = bos['direction']  # 2순위
                else:
                    daily_bias = 'neutral'

                structure_1d = {
                    'pdh': pdh, 'pdl': pdl, 'pwh': pwh, 'pwl': pwl,
                    'sweep_bias': sweep_bias or 'none',
                    'sweep_note': sweep_note,
                    'orderflow':  orderflow,
                    'bos_event':  bos['last_event'],
                    'bos_level':  round(bos['level'], 2) if bos['level'] else None,
                    'bos_direction': bos['direction'],
                    'eq_high': eq_high, 'eq_low': eq_low,
                    'equilibrium': equilibrium,
                    'price_zone': price_zone,
                    'fvgs_1d': fvg_summary,
                    'daily_bias': daily_bias,
                }
        except Exception as e:
            structure_1d = {'error': str(e)}

        # ── 4H 오더플로우 (순수 ICT: 스윙구조·BOS/MSS·FVG) ──────
        structure_4h = {}
        try:
            df_4h = self.agent.fetcher.fetch_ohlcv(symbol, '4h', 60)
            if df_4h is not None and len(df_4h) >= 15:
                try:
                    from core.ict_engine import ICTEngine
                    engine = ICTEngine()
                    # 스윙 구조 (HH/HL vs LH/LL)
                    swings4h = engine.detect_swing_structure(df_4h, swing_window=3, lookback=3)
                    # BOS/MSS
                    bos4h = engine.detect_bos_mss(df_4h, swing_window=3)
                    # 4H FVG 최근 3개
                    fvgs4h = engine.detect_fvg(df_4h)
                    fvg4h_summary = [
                        {'type': f['type'], 'top': round(f['top'], 2), 'btm': round(f['bottom'], 2)}
                        for f in fvgs4h[-3:]
                    ] if fvgs4h else []
                    # 최근 4H 고저 (유동성 레벨)
                    prev4h_high = round(float(df_4h.iloc[-2]['high']), 2)
                    prev4h_low  = round(float(df_4h.iloc[-2]['low']),  2)
                except Exception:
                    swings4h = {'structure': 'sideways', 'hh': False, 'hl': False, 'lh': False, 'll': False}
                    bos4h    = {'direction': 'neutral', 'last_event': None, 'level': None}
                    fvg4h_summary = []
                    prev4h_high = prev4h_low = 0

                if swings4h.get('hh') and swings4h.get('hl'):
                    orderflow4h = 'bullish (HH·HL)'
                elif swings4h.get('lh') and swings4h.get('ll'):
                    orderflow4h = 'bearish (LH·LL)'
                else:
                    orderflow4h = 'sideways / mixed'

                structure_4h = {
                    'orderflow':    orderflow4h,
                    'bos_direction': bos4h['direction'],
                    'bos_event':    bos4h['last_event'],
                    'bos_level':    round(bos4h['level'], 2) if bos4h.get('level') else None,
                    'fvgs_4h':      fvg4h_summary,
                    'prev_high':    prev4h_high,
                    'prev_low':     prev4h_low,
                }
        except Exception as e:
            structure_4h = {'error': str(e)}

        # ── 15m 유동성 스윕 ────────────────────────────────────────
        sweep_15m = {}
        try:
            df_15m = self.agent.fetcher.fetch_ohlcv(symbol, '15m', 60)
            if df_15m is not None and len(df_15m) >= 25:
                try:
                    from core.ict_engine import ICTEngine
                    engine = ICTEngine()
                    sweeps = engine.detect_liquidity_sweeps(df_15m, lookback=20)
                    recent = sweeps[-1] if sweeps else None
                except Exception:
                    recent = None
                # 최근 15m FVG
                try:
                    fvgs = engine.detect_fvg(df_15m)
                    recent_fvg = fvgs[-1] if fvgs else None
                except Exception:
                    recent_fvg = None
                sweep_15m = {
                    'recent_sweep': recent['type'] if recent else '없음',
                    'recent_fvg_type': recent_fvg['type'] if recent_fvg else '없음',
                    'recent_fvg_top': round(recent_fvg['top'], 2) if recent_fvg else None,
                    'recent_fvg_bottom': round(recent_fvg['bottom'], 2) if recent_fvg else None,
                }
        except Exception as e:
            sweep_15m = {'error': str(e)}

        # ── 펀딩피 (Bybit, ccxt) ──────────────────────────────────
        funding = {}
        try:
            perp = symbol if ':' in symbol else f"{symbol}:{symbol.split('/')[1]}"
            fr = self.agent.fetcher.exchange.fetch_funding_rate(perp)
            rate = round(float(fr.get('fundingRate', 0)) * 100, 4)
            if rate > 0.05:
                bias = '롱 과열 (숏 스퀴즈 경계)'
            elif rate < -0.03:
                bias = '숏 과열 (롱 스퀴즈 경계)'
            else:
                bias = '중립'
            funding = {'rate_pct': rate, 'bias': bias}
        except Exception:
            funding = {}

        # ── Fear & Greed Index (Alternative.me) ──────────────────
        fng = {}
        try:
            import urllib.request
            with urllib.request.urlopen('https://api.alternative.me/fng/?limit=1', timeout=5) as r:
                d = json.loads(r.read())['data'][0]
                val = int(d['value'])
                cls = d['value_classification']
                if val <= 25:   signal = '극단 공포 → 롱 바이어스 강화'
                elif val <= 45: signal = '공포 → 롱 우세'
                elif val <= 55: signal = '중립'
                elif val <= 75: signal = '탐욕 → 숏 경계'
                else:           signal = '극단 탐욕 → 숏 바이어스 강화'
                fng = {'value': val, 'label': cls, 'signal': signal}
        except Exception:
            fng = {}

        # ── BTC 도미넌스 (CoinGecko, 무료) ───────────────────────
        btc_dom = {}
        try:
            import urllib.request
            with urllib.request.urlopen(
                'https://api.coingecko.com/api/v3/global', timeout=5
            ) as r:
                g = json.loads(r.read())['data']
                dom = round(g['market_cap_percentage'].get('btc', 0), 2)
                btc_dom = {'dominance_pct': dom}
        except Exception:
            btc_dom = {}

        # ── 바이낸스 선물 퍼블릭 API (무료, 키 없음) ─────────────
        bnb = {}
        try:
            import urllib.request as _ur
            base = symbol.split('/')[0]          # 'BTC/USDT' → 'BTC'
            sym  = f'{base}USDT'                 # 바이낸스 심볼

            def _bnb(path, params=''):
                url = f'https://fapi.binance.com/fapi/v1/{path}?{params}'
                req = _ur.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with _ur.urlopen(req, timeout=6) as r:
                    return json.loads(r.read())

            # 1) 바이낸스 OI
            oi_bnb = {}
            try:
                d = _bnb('openInterest', f'symbol={sym}')
                oi_val = float(d.get('openInterest', 0))
                # 현재가 곱해서 달러 환산
                oi_usd = round(oi_val * price / 1e9, 3)
                oi_bnb = {'oi_contracts': round(oi_val, 0), 'oi_usd_b': oi_usd}
            except Exception:
                pass

            # 2) 바이낸스 펀딩피 (최신)
            fund_bnb = {}
            try:
                d = _bnb('fundingRate', f'symbol={sym}&limit=1')
                if d:
                    rate = round(float(d[-1].get('fundingRate', 0)) * 100, 4)
                    fund_bnb = {'rate_pct': rate}
            except Exception:
                pass

            # 3) 상위 트레이더 L/S 포지션 비율 (고래 포지션)
            top_ls = {}
            try:
                d = _bnb('topLongShortPositionRatio', f'symbol={sym}&period=1h&limit=2')
                if d:
                    latest = d[-1]
                    ratio  = float(latest.get('longShortRatio', 1))
                    long_p = float(latest.get('longAccount', 0.5))
                    top_ls = {
                        'ratio': round(ratio, 3),
                        'long_pct': round(long_p * 100, 1),
                        'bias': '고래 롱 우세' if ratio > 1.2 else '고래 숏 우세' if ratio < 0.8 else '고래 중립',
                    }
            except Exception:
                pass

            # 4) 테이커 매수/매도 거래량 (CVD 대체 — 3봉 합산)
            taker = {}
            try:
                d = _bnb('takerbuyselltvolume', f'symbol={sym}&period=1h&limit=3')
                if d:
                    buy_vol  = sum(float(r.get('buyVol',  0)) for r in d)
                    sell_vol = sum(float(r.get('sellVol', 0)) for r in d)
                    total    = buy_vol + sell_vol
                    buy_pct  = round(buy_vol / total * 100, 1) if total else 50
                    delta    = round(buy_vol - sell_vol, 0)
                    taker = {
                        'buy_pct': buy_pct,
                        'delta_usd': delta,
                        'pressure': '강한 매수 우세' if buy_pct > 55 else '강한 매도 우세' if buy_pct < 45 else '균형',
                    }
            except Exception:
                pass

            # 5) 대형 청산 주문 (최근 24h, 롱/숏 청산 합산)
            liq_force = {}
            try:
                d = _bnb('allForceOrders', f'symbol={sym}&limit=100')
                if d:
                    long_liq  = sum(float(o['origQty']) * float(o['price'])
                                    for o in d if o.get('side') == 'SELL') / 1e6
                    short_liq = sum(float(o['origQty']) * float(o['price'])
                                    for o in d if o.get('side') == 'BUY') / 1e6
                    liq_force = {
                        'long_liq_m':  round(long_liq, 2),
                        'short_liq_m': round(short_liq, 2),
                        'dominant': '롱 청산 우세 → SSL 스윕 가능성' if long_liq > short_liq
                                    else '숏 청산 우세 → BSL 스윕 가능성',
                    }
            except Exception:
                pass

            bnb = {
                'oi': oi_bnb,
                'funding': fund_bnb,
                'top_ls': top_ls,
                'taker': taker,
                'liquidations': liq_force,
            }
        except Exception as e:
            bnb = {'error': str(e)}

        return {
            'symbol': symbol, 'price': price,
            'oi': oi_data, 'ls': ls_data, 'position': pos,
            'structure_1d': structure_1d,
            'structure_4h': structure_4h,
            'sweep_15m': sweep_15m,
            'funding': funding,
            'fng': fng,
            'btc_dom': btc_dom,
            'bnb': bnb,
        }

    # ── 대화 처리 (모델 분기) ─────────────────────────────────────
    # 모델 ID → 제공사 구분
    @staticmethod
    def _provider(model_id: str) -> str:
        return 'gemini' if model_id.startswith('gemini') else 'claude'

    def chat(self, session_id: str, user_text: str,
             images: list = None,
             symbol: str = 'BTC/USDT', model: str = 'claude-sonnet-4-6') -> dict:
        images = images or []

        if session_id not in self._sessions:
            self._sessions[session_id] = {'claude': [], 'gemini': []}

        snap = self.get_market_snapshot(symbol)
        s1d  = snap.get('structure_1d', {})
        s4h  = snap.get('structure_4h', {})
        s15m = snap.get('sweep_15m', {})
        fund = snap.get('funding', {})
        fng  = snap.get('fng', {})
        bdom = snap.get('btc_dom', {})
        bnb  = snap.get('bnb', {})

        def _fmt(v, fmt='.2f'):
            return f'{v:{fmt}}' if isinstance(v, (int, float)) else str(v or 'N/A')

        import time as _time
        import datetime as _dt
        kst_now = _dt.datetime.utcnow() + _dt.timedelta(hours=9)
        kst_str = kst_now.strftime('%Y-%m-%d %H:%M KST')
        kst_hour = kst_now.hour
        if 15 <= kst_hour < 17:
            killzone = '🟢 런던 킬존 (15:00–17:00 KST) — 활성'
        elif 22 <= kst_hour or kst_hour < 1:
            killzone = '🟢 뉴욕 킬존 (22:00–01:00 KST) — 활성'
        elif 0 <= kst_hour < 4:
            killzone = '🟡 아시안 킬존 (00:00–04:00 KST) — 활성'
        else:
            killzone = f'⚪ 킬존 외 대기 구간 — 다음: {"런던 15:00" if kst_hour < 15 else "뉴욕 22:00"} KST'

        market_ctx = (
            f"\n\n[자동 수집 시장 데이터 — {symbol}]\n"
            f"현재 시각: {kst_str}\n"
            f"킬존 상태: {killzone}\n"
            f"현재가: {snap['price']:,.2f} USDT\n"
            f"OI 변화: {snap['oi'].get('oi_change_pct', 'N/A')}% ({snap['oi'].get('trend', 'N/A')})\n"
            f"L/S 비율: {snap['ls'].get('current_ratio', 'N/A')} ({snap['ls'].get('bias', 'N/A')})\n"
            f"현재 포지션: {json.dumps(snap['position'], ensure_ascii=False) if snap['position'] else '없음'}\n"
            f"\n[외부 시장 지표]\n"
            f"  공포/탐욕 지수: {fng.get('value','N/A')} ({fng.get('label','N/A')}) → {fng.get('signal','N/A')}\n"
            f"  펀딩피: {fund.get('rate_pct','N/A')}% → {fund.get('bias','N/A')}\n"
            f"  BTC 도미넌스: {bdom.get('dominance_pct','N/A')}%\n"
            f"\n[1D 데일리 바이어스 — 순수 ICT]\n"
            f"  ★ 종합 바이어스: {s1d.get('daily_bias','?').upper()}\n"
            f"  [1순위 유동성 스윕] {s1d.get('sweep_note','?')}\n"
            f"  PDH: {_fmt(s1d.get('pdh'))} / PDL: {_fmt(s1d.get('pdl'))} "
            f"| PWH: {_fmt(s1d.get('pwh'))} / PWL: {_fmt(s1d.get('pwl'))}\n"
            f"  [2순위 오더플로우] {s1d.get('orderflow','?')} "
            f"| {s1d.get('bos_event','?')} @ {_fmt(s1d.get('bos_level'))}\n"
            f"  [3순위 PD Array] Equilibrium: {_fmt(s1d.get('equilibrium'))} "
            f"(Range {_fmt(s1d.get('eq_low'))}~{_fmt(s1d.get('eq_high'))}) "
            f"→ 현재가 {s1d.get('price_zone','?').upper()} Zone\n"
            + (f"  1D FVG: " + ", ".join(
                f"{f['type']}({f['btm']}~{f['top']})" for f in s1d.get('fvgs_1d',[])
               ) + "\n" if s1d.get('fvgs_1d') else "")
            + f"\n[4H 오더플로우 — 순수 ICT]\n"
            f"  스윙 구조: {s4h.get('orderflow','?')}\n"
            f"  BOS/MSS: {s4h.get('bos_direction','?')} ({s4h.get('bos_event','?')} @ {_fmt(s4h.get('bos_level'))})\n"
            f"  이전 4H 고점: {_fmt(s4h.get('prev_high'))} / 저점: {_fmt(s4h.get('prev_low'))}\n"
            + (f"  4H FVG: " + ", ".join(
                f"{f['type']}({f['btm']}~{f['top']})" for f in s4h.get('fvgs_4h', [])
               ) + "\n" if s4h.get('fvgs_4h') else "")
            + f"\n[15m 유동성 스윕]\n"
            f"  최근 스윕: {s15m.get('recent_sweep','?')}\n"
            f"  최근 FVG: {s15m.get('recent_fvg_type','?')} "
            f"(Top: {_fmt(s15m.get('recent_fvg_top'))} / Bottom: {_fmt(s15m.get('recent_fvg_bottom'))})\n"
            + (
            f"\n[바이낸스 선물 — 오더플로우]\n"
            f"  OI: {bnb.get('oi',{}).get('oi_usd_b','N/A')}B$ "
            f"| 펀딩피: {bnb.get('funding',{}).get('rate_pct','N/A')}%\n"
            f"  고래 포지션: {bnb.get('top_ls',{}).get('bias','N/A')} "
            f"(롱 {bnb.get('top_ls',{}).get('long_pct','N/A')}%)\n"
            f"  테이커 압력(3h): {bnb.get('taker',{}).get('pressure','N/A')} "
            f"(매수 {bnb.get('taker',{}).get('buy_pct','N/A')}%)\n"
            f"  대형 청산: 롱청산 {bnb.get('liquidations',{}).get('long_liq_m','N/A')}M$ / "
            f"숏청산 {bnb.get('liquidations',{}).get('short_liq_m','N/A')}M$ "
            f"→ {bnb.get('liquidations',{}).get('dominant','N/A')}\n"
            if bnb and 'error' not in bnb else ''
            )
        )

        provider = self._provider(model)
        if provider == 'gemini':
            reply_text = self._chat_gemini(session_id, user_text, images, market_ctx, model)
        else:
            reply_text = self._chat_claude(session_id, user_text, images, market_ctx, model)

        suggestion = self._parse_suggestion(reply_text, snap['price'])

        # ── 채팅 로그 기록 ────────────────────────────────────────
        import datetime as _dt
        _kst_now = _dt.datetime.utcnow() + _dt.timedelta(hours=9)
        if session_id not in self._chat_logs:
            self._chat_logs[session_id] = {
                'session_id': session_id,
                'symbol': symbol,
                'model': model,
                'started_at': _kst_now.strftime('%Y-%m-%d %H:%M:%S'),
                'messages': [],
            }
        log = self._chat_logs[session_id]
        ts = _kst_now.strftime('%H:%M:%S')
        if user_text:
            log['messages'].append({'role': 'user', 'text': user_text, 'ts': ts,
                                     'images': len(images)})
        log['messages'].append({'role': 'assistant', 'text': reply_text, 'ts': ts})
        log['symbol'] = symbol
        log['model']  = model
        self._save_chat_log(session_id)

        return {'reply': reply_text, 'suggestion': suggestion, 'market': snap, 'model': model}

    # ── Claude 대화 ───────────────────────────────────────────────
    def _chat_claude(self, session_id: str, user_text: str,
                     images: list, market_ctx: str,
                     model_id: str = 'claude-sonnet-4-6') -> str:
        if not self._claude_client:
            raise ValueError("ANTHROPIC_API_KEY가 .env에 설정되지 않았습니다.")

        history = self._sessions[session_id]['claude']
        full_text = user_text + market_ctx

        if images:
            content = []
            for img in images:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": img.get('mime', 'image/png'), "data": img['b64']}
                })
            content.append({"type": "text", "text": full_text})
        else:
            content = full_text

        history.append({"role": "user", "content": content})

        response = self._claude_client.messages.create(
            model=model_id,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=history,
        )
        reply = response.content[0].text
        history.append({"role": "assistant", "content": reply})

        if len(history) > 60:
            self._sessions[session_id]['claude'] = history[-60:]

        return reply

    # ── Gemini 대화 ───────────────────────────────────────────────
    def _chat_gemini(self, session_id: str, user_text: str,
                     images: list, market_ctx: str,
                     model_id: str = 'gemini-3.1-pro-preview') -> str:
        if not self._gemini_client:
            raise ValueError("GEMINI_API_KEY가 .env에 설정되지 않았습니다.")

        try:
            import base64
            from google.genai import types as gtypes

            history = self._sessions[session_id]['gemini']
            full_text = user_text + market_ctx

            parts = []
            for img in images:
                img_bytes = base64.b64decode(img['b64'])
                parts.append(gtypes.Part.from_bytes(data=img_bytes, mime_type=img.get('mime', 'image/png')))
            parts.append(gtypes.Part.from_text(text=full_text))

            contents = list(history) + [gtypes.Content(role='user', parts=parts)]

            response = self._gemini_client.models.generate_content(
                model=model_id,
                contents=contents,
                config=gtypes.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.7,
                    max_output_tokens=8096,
                ),
            )
            reply = response.text

            history.append(gtypes.Content(role='user', parts=parts))
            history.append(gtypes.Content(role='model', parts=[gtypes.Part.from_text(text=reply)]))
            if len(history) > 60:
                self._sessions[session_id]['gemini'] = history[-60:]

            return reply
        except Exception as e:
            raise RuntimeError(f"Gemini 오류: {e}")

    # ── SL/TP 파싱 ────────────────────────────────────────────────
    def _parse_suggestion(self, text: str, current_price: float) -> Optional[dict]:
        import re
        sl_match = re.search(r'(?:SL|손절)[:\s]*([0-9,]+(?:\.[0-9]+)?)', text)
        tp_match = re.search(r'(?:TP|익절)[:\s]*([0-9,]+(?:\.[0-9]+)?)', text)
        side_long  = any(w in text for w in ['롱', 'LONG', 'long', '매수', 'buy'])
        side_short = any(w in text for w in ['숏', 'SHORT', 'short', '매도', 'sell'])

        if not sl_match and not tp_match:
            return None

        def _parse_num(m):
            try:
                return float(m.group(1).replace(',', '')) if m else None
            except Exception:
                return None

        sl = _parse_num(sl_match)
        tp = _parse_num(tp_match)
        if sl is None and tp is None:
            return None

        side = None
        if side_long and not side_short:
            side = 'buy'
        elif side_short and not side_long:
            side = 'sell'

        # TP는 SL 기준 1:3 고정 (current_price 기준)
        if sl is not None and current_price > 0:
            risk = abs(current_price - sl)
            if side == 'sell':
                tp = round(current_price - risk * 3, 4)
            else:
                tp = round(current_price + risk * 3, 4)

        return {'sl': sl, 'tp': tp, 'side': side}

    # ── 거래 실행 ─────────────────────────────────────────────────
    def execute_trade(self, symbol: str, side: str, sl: float, tp: float,
                      session_id: str = None, model: str = 'claude') -> dict:
        try:
            df = self.agent.fetcher.fetch_ohlcv(symbol, '1h', 100)
            if df is None or df.empty:
                return {'success': False, 'message': '가격 데이터 조회 실패'}

            current_price = float(df.iloc[-1]['close'])
            balance = self.agent.fetcher.fetch_balance('USDT')
            if not balance:
                return {'success': False, 'message': '잔고 조회 실패'}

            risk_report = self.agent.risk_manager.calculate_position_size(balance, current_price, sl)
            qty = risk_report['position_qty']
            lev = max(2, int(risk_report['required_leverage']) + 1)

            order = self.agent.executor.place_order(symbol, side, qty, lev, stop_loss=sl, take_profit=tp)
            if not order:
                return {'success': False, 'message': '주문 실패 (거래소 응답 없음)'}

            import time as _t
            entry = {
                'time':        _t.strftime('%m/%d %H:%M'),
                'ts':          int(_t.time() * 1000),
                'symbol':      symbol,
                'side':        side.upper(),
                'qty':         f'{qty:.6f}',
                'entry_price': round(current_price, 4),
                'sl':          sl,
                'tp':          tp,
                'account':     'core',
                'pnl':         None,
                'exit_price':  None,
                'source':      f'assistant_{model}',
            }
            self.agent._append_trade_log(entry)

            # 실행 후 대화에 결과 기록
            if session_id and session_id in self._sessions:
                exec_msg = (
                    f"[시스템] 거래 실행 완료 ✅\n"
                    f"{symbol} {side.upper()} | 진입가: {current_price:,.4f}\n"
                    f"수량: {qty:.6f} | 레버리지: {lev}x | SL: {sl} | TP: {tp}"
                )
                if self._provider(model) == 'gemini' and self._gemini_client:
                    try:
                        from google.genai import types as gtypes
                        history = self._sessions[session_id]['gemini']
                        contents = list(history) + [gtypes.Content(role='user', parts=[gtypes.Part.from_text(text=exec_msg)])]
                        resp = self._gemini_client.models.generate_content(
                            model=model,
                            contents=contents,
                            config=gtypes.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, max_output_tokens=256),
                        )
                        confirm_text = resp.text
                        history.append(gtypes.Content(role='user', parts=[gtypes.Part.from_text(text=exec_msg)]))
                        history.append(gtypes.Content(role='model', parts=[gtypes.Part.from_text(text=confirm_text)]))
                    except Exception:
                        confirm_text = f"{symbol} {side.upper()} 진입 완료. 포지션을 모니터링합니다."
                elif self._claude_client:
                    history = self._sessions[session_id]['claude']
                    history.append({"role": "user", "content": exec_msg})
                    confirm = self._claude_client.messages.create(
                        model=model,
                        max_tokens=256,
                        system=SYSTEM_PROMPT,
                        messages=history,
                    )
                    confirm_text = confirm.content[0].text
                    history.append({"role": "assistant", "content": confirm_text})
                else:
                    confirm_text = f"{symbol} {side.upper()} 진입 완료."
            else:
                confirm_text = f"{symbol} {side.upper()} 진입 완료. 포지션을 모니터링합니다."

            return {
                'success': True,
                'message': confirm_text,
                'order_id': order.get('id', ''),
                'qty': qty,
                'leverage': lev,
                'entry_price': current_price,
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    # ── 포지션 청산 ───────────────────────────────────────────────
    def close_position(self, symbol: str, session_id: str = None) -> dict:
        try:
            positions = self.agent.fetcher.fetch_positions(symbols=[symbol])
            pos = positions.get(symbol)
            if not pos:
                return {'success': False, 'message': f'{symbol} 열린 포지션 없음'}

            close_side = 'sell' if pos['side'].lower() == 'long' else 'buy'
            qty = pos['size']
            contract_symbol = symbol if ':' in symbol else f"{symbol}:{symbol.split('/')[1]}"
            order = self.agent.fetcher.exchange.create_order(
                symbol=contract_symbol,
                type='market',
                side=close_side,
                amount=qty,
                params={'reduceOnly': True}
            )
            return {'success': True, 'message': f'{symbol} 포지션 청산 완료 (수량: {qty})', 'order_id': order.get('id', '')}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def clear_session(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]
        if session_id in self._chat_logs:
            del self._chat_logs[session_id]

    # ── 채팅 로그 저장/조회 ───────────────────────────────────────
    def _save_chat_log(self, session_id: str):
        """현재 세션 로그를 JSON 파일로 저장"""
        try:
            log = self._chat_logs.get(session_id)
            if not log:
                return
            import time as _t
            date_str = log['started_at'][:10]  # 'YYYY-MM-DD'
            filename = f"{date_str}_{session_id[-8:]}.json"
            path = os.path.join(self._log_dir, filename)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(log, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_chat_log(self, session_id: str) -> dict:
        """세션 로그 반환 (메모리 우선, 없으면 파일에서 탐색)"""
        if session_id in self._chat_logs:
            return self._chat_logs[session_id]
        # 파일에서 탐색
        suffix = session_id[-8:]
        for fname in os.listdir(self._log_dir):
            if suffix in fname and fname.endswith('.json'):
                try:
                    with open(os.path.join(self._log_dir, fname), encoding='utf-8') as f:
                        return json.load(f)
                except Exception:
                    pass
        return {}

    def list_chat_logs(self) -> list:
        """저장된 채팅 로그 목록 반환 (최신순)"""
        logs = []
        for fname in sorted(os.listdir(self._log_dir), reverse=True):
            if not fname.endswith('.json'):
                continue
            try:
                path = os.path.join(self._log_dir, fname)
                with open(path, encoding='utf-8') as f:
                    d = json.load(f)
                logs.append({
                    'filename': fname,
                    'session_id': d.get('session_id', ''),
                    'symbol': d.get('symbol', ''),
                    'model': d.get('model', ''),
                    'started_at': d.get('started_at', ''),
                    'message_count': len(d.get('messages', [])),
                })
            except Exception:
                pass
        return logs
