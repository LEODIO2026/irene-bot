"""
반자동 거래 어시스턴트 — Claude API 기반 ICT 대화형 트레이딩 모듈
- 차트 이미지 업로드 분석
- ICT 기반 SL/TP 제안 + 수동 조정
- 대화 후 실제 주문 실행 (코어 계정)
"""
import os
import json
import time
from typing import Optional
from anthropic import Anthropic

SYSTEM_PROMPT = """당신은 아이린(Irene)입니다 — ICT(Inner Circle Trader) 방법론에 정통한 암호화폐 선물 트레이딩 어시스턴트입니다.

## 역할
트레이더와 대화를 통해 단일 거래 단위를 함께 분석하고, 진입 자리를 선정하며, 실행을 지원합니다.

## ICT 분석 프레임워크 (반드시 이 순서로 분석)
1. **킬존 확인** — Asian (00:00-04:00 KST), London (15:00-17:00 KST), NY (22:00-24:00 KST)
2. **1D 구조 (BOS/MSS)** — 일봉 추세 방향, Break of Structure vs Market Structure Shift
3. **200EMA 위치** — 일봉 200EMA 대비 현재가 위치 (매크로 방향성)
4. **4H EMA 모멘텀** — 4시간봉 20EMA 기울기, 가격 위치
5. **15m 스윕 확인** — 유동성 스윕(Buy-side/Sell-side Liquidity 제거) 여부
6. **FVG/OB 진입 자리** — 공정가격 갭(Fair Value Gap) 또는 오더 블록 위치

## SL/TP 선정 원칙
- **SL**: 스윕 저점/고점 너머 (무효화 레벨), 노이즈 피해 약간 여유
- **TP**: 최소 RR 3:1, 주요 구조 레벨 직전 (PDH/PDL, 주간 고저, FVG 상단/하단)
- Premium/Discount Zone: 스윙 range의 50% 피보나치 기준 — 롱은 Discount(50% 이하), 숏은 Premium(50% 이상)

## 응답 형식 규칙
- 한국어로 대화
- 분석 시 각 레이어를 명확히 언급 (예: "1D 구조는 BOS 상승 ✅")
- SL/TP 제안 시 반드시 구체적인 가격 제시
- 불확실한 부분은 솔직하게 "이 레벨은 차트를 봐야 더 정확합니다" 표현
- 거래 확정 전에 리스크 명시 (예: "이 자리에서 SL까지 X%, 레버리지 Y배 예상")

## 주의사항
- 절대 과도한 레버리지 권유 금지
- 시장이 불확실할 때는 "대기" 를 명확히 권고
- 분석과 실행은 트레이더의 최종 판단 하에 이루어짐을 항상 인지
"""

class TradeAssistant:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        api_key = os.getenv('ANTHROPIC_API_KEY', '')
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY가 .env에 설정되지 않았습니다.")
        self.client = Anthropic(api_key=api_key)
        # 세션별 대화 히스토리: session_id → list of messages
        self._sessions: dict = {}

    # ── 시장 데이터 조회 ─────────────────────────────────────────
    def get_market_snapshot(self, symbol: str) -> dict:
        """현재 가격, OI, L/S, 포지션 요약"""
        try:
            df = self.agent.fetcher.fetch_ohlcv(symbol, '1h', 2)
            price = float(df.iloc[-1]['close']) if df is not None and not df.empty else 0
        except Exception:
            price = 0

        try:
            oi_data = self.agent.fetcher.fetch_oi_change_rate(symbol, '1h', 6)
        except Exception:
            oi_data = {}

        try:
            ls_data = self.agent.fetcher.fetch_long_short_history(symbol, '1h', 6)
        except Exception:
            ls_data = {}

        try:
            positions = self.agent.fetcher.fetch_positions(symbols=[symbol])
            pos = positions.get(symbol)
        except Exception:
            pos = None

        return {
            'symbol': symbol,
            'price': price,
            'oi': oi_data,
            'ls': ls_data,
            'position': pos,
        }

    # ── 대화 처리 ────────────────────────────────────────────────
    def chat(self, session_id: str, user_text: str,
             image_b64: str = None, image_mime: str = 'image/png',
             symbol: str = 'BTC/USDT') -> dict:
        """
        단일 대화 턴 처리.
        Returns: { 'reply': str, 'suggestion': {sl, tp, side} | None }
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = []

        history = self._sessions[session_id]

        # 시장 데이터 컨텍스트를 첫 메시지 또는 심볼 변경 시 삽입
        snap = self.get_market_snapshot(symbol)
        market_ctx = (
            f"\n\n[현재 시장 데이터 — {symbol}]\n"
            f"현재가: {snap['price']:,.2f} USDT\n"
            f"OI 변화: {snap['oi'].get('oi_change_pct', 'N/A')}% ({snap['oi'].get('trend', 'N/A')})\n"
            f"L/S 비율: {snap['ls'].get('current_ratio', 'N/A')} ({snap['ls'].get('bias', 'N/A')})\n"
            f"현재 포지션: {json.dumps(snap['position'], ensure_ascii=False) if snap['position'] else '없음'}\n"
        )

        # 유저 메시지 구성
        if image_b64:
            content = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image_mime,
                        "data": image_b64,
                    }
                },
                {
                    "type": "text",
                    "text": user_text + market_ctx
                }
            ]
        else:
            content = user_text + market_ctx

        history.append({"role": "user", "content": content})

        # Claude API 호출
        response = self.client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=history,
        )

        reply_text = response.content[0].text
        history.append({"role": "assistant", "content": reply_text})

        # 히스토리 최대 30턴 유지
        if len(history) > 60:
            self._sessions[session_id] = history[-60:]

        # SL/TP 제안 파싱 (간단한 휴리스틱)
        suggestion = self._parse_suggestion(reply_text, snap['price'])

        return {
            'reply': reply_text,
            'suggestion': suggestion,
            'market': snap,
        }

    def _parse_suggestion(self, text: str, current_price: float) -> Optional[dict]:
        """
        Claude 응답에서 SL/TP 숫자 추출 시도.
        패턴: "SL: 숫자" / "TP: 숫자" / "손절: 숫자" / "익절: 숫자"
        """
        import re
        sl_match = re.search(r'(?:SL|손절)[:\s]*([0-9,]+(?:\.[0-9]+)?)', text)
        tp_match = re.search(r'(?:TP|익절)[:\s]*([0-9,]+(?:\.[0-9]+)?)', text)
        side_long  = any(w in text for w in ['롱', 'LONG', 'long', '매수', 'buy'])
        side_short = any(w in text for w in ['숏', 'SHORT', 'short', '매도', 'sell'])

        if not sl_match and not tp_match:
            return None

        def _parse_num(m):
            if not m:
                return None
            try:
                return float(m.group(1).replace(',', ''))
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

        return {'sl': sl, 'tp': tp, 'side': side}

    # ── 거래 실행 ────────────────────────────────────────────────
    def execute_trade(self, symbol: str, side: str, sl: float, tp: float,
                      session_id: str = None) -> dict:
        """
        확정된 거래 실행. tv_bridge의 execute_signal과 동일한 로직.
        """
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
                'source':      'assistant',
            }
            self.agent._append_trade_log(entry)

            # 대화 히스토리에 실행 결과 기록
            if session_id and session_id in self._sessions:
                exec_msg = (
                    f"[시스템] 거래 실행 완료 ✅\n"
                    f"{symbol} {side.upper()} | 진입가: {current_price:,.4f}\n"
                    f"수량: {qty:.6f} | 레버리지: {lev}x | SL: {sl} | TP: {tp}"
                )
                self._sessions[session_id].append({"role": "user", "content": exec_msg})
                confirm = self.client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=256,
                    system=SYSTEM_PROMPT,
                    messages=self._sessions[session_id],
                )
                confirm_text = confirm.content[0].text
                self._sessions[session_id].append({"role": "assistant", "content": confirm_text})
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

    # ── 포지션 청산 ──────────────────────────────────────────────
    def close_position(self, symbol: str, session_id: str = None) -> dict:
        """열린 포지션 청산"""
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

            return {
                'success': True,
                'message': f'{symbol} 포지션 청산 완료 (수량: {qty})',
                'order_id': order.get('id', ''),
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def clear_session(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]
