import os
import asyncio
import threading
import base64
import time
from io import BytesIO
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

load_dotenv()

class TelegramBot:
    """
    아이린 텔레그램 봇 — 알림 전송 + 양방향 대화 지원
    """
    def __init__(self, agent_instance=None):
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.agent = agent_instance
        self.app = None
        self._loop = None
        # 기본 모델 설정 (Claude 4.6 Sonnet)
        self.current_model = 'claude-sonnet-4-6'

        if not self.token:
            print("⚠️ TELEGRAM_BOT_TOKEN이 설정되지 않았습니다.")
            return

        # App은 __init__에서 동기 빌드 (이벤트 루프 불필요)
        self.app = ApplicationBuilder().token(self.token).build()
        self._setup_handlers()

    def _setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self._start_command))
        self.app.add_handler(CommandHandler("help", self._help_command))
        self.app.add_handler(CommandHandler("model", self._model_command))
        self.app.add_handler(CallbackQueryHandler(self._model_callback))
        self.app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self._handle_message))
        self.app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

    # ── 핸들러 로직 ──────────────────────────────────────────
    
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        msg = (
            f"반가워요! 아이린 트레이딩 비서예요. 😊\n\n"
            f"오빠의 채팅 ID는 <code>{chat_id}</code> 네요!\n"
            f"이제 제가 시장을 감시하면서 중요한 순간에 알림을 드릴게요.\n\n"
            f"저랑 대화하고 싶으시면 언제든 말을 걸어주세요!"
        )
        await update.message.reply_html(msg)

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = (
            "<b>아이린 텔레그램 사용법:</b>\n"
            "• 그냥 말을 걸면 현재 시장 상황에 대해 대화할 수 있어요.\n"
            "• 차트 캡처 이미지를 보내면 분석해 드릴게요.\n"
            "• /model 명령어로 AI 모델을 변경할 수 있어요.\n"
            "• 알림이 오면 대시보드 링크를 통해 거래를 승인하세요."
        )
        await update.message.reply_html(msg)

    async def _model_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """AI 모델 선택 메뉴 출력"""
        if not self.agent or str(update.effective_chat.id) != self.chat_id:
            return

        keyboard = [
            [
                InlineKeyboardButton("🧠 Claude 4.6 Opus", callback_data='claude-opus-4-6'),
                InlineKeyboardButton("⚡ Claude 4.6 Sonnet", callback_data='claude-sonnet-4-6'),
            ],
            [
                InlineKeyboardButton("💎 Gemini 3.1 Pro", callback_data='gemini-3.1-pro-preview'),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"현재 모델: <b>{self.current_model}</b>\n변경할 모델을 선택해 주세요:",
            reply_markup=reply_markup,
            parse_mode='HTML'
        )

    async def _model_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """모델 선택 결과 처리"""
        query = update.callback_query
        await query.answer()

        selected_model = query.data
        self.current_model = selected_model

        await query.edit_message_text(
            text=f"✅ 모델이 <b>{selected_model}</b>(으)로 변경되었습니다! 이제 이 모델로 분석해 드릴게요. 😊",
            parse_mode='HTML'
        )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """텍스트 메시지 처리 — TradeAssistant와 연동"""
        if not self.agent or str(update.effective_chat.id) != self.chat_id:
            return

        user_text = update.message.text
        # 아이린 모드 작동 알림
        await context.bot.send_chat_action(chat_id=self.chat_id, action="typing")
        
        try:
            # TVBridge가 관리하는 assistant 인스턴스 사용
            assistant = self.agent.bridge.assistant
            result = assistant.chat(
                session_id=f"tg_{self.chat_id}",
                user_text=user_text,
                symbol=self.agent.symbols[0], # 기본 심볼
                model=self.current_model
            )
            reply = result.get('reply', '음... 뭐라고 답해야 할지 모르겠어요. 😅')
            await update.message.reply_html(reply)
        except Exception as e:
            await update.message.reply_text(f"❌ 오류가 발생했어요: {str(e)}")

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """이미지 메시지 처리 — 차트 분석"""
        if not self.agent or str(update.effective_chat.id) != self.chat_id:
            return

        await context.bot.send_chat_action(chat_id=self.chat_id, action="upload_photo")
        
        try:
            # 최고 해상도 사진 가져오기
            photo_file = await update.message.photo[-1].get_file()
            img_bytearray = await photo_file.download_as_bytearray()
            img_b64 = base64.b64encode(img_bytearray).decode('utf-8')
            
            user_text = update.message.caption or "이 차트 분석해줘"
            
            assistant = self.agent.bridge.assistant
            result = assistant.chat(
                session_id=f"tg_{self.chat_id}",
                user_text=user_text,
                images=[{'b64': img_b64, 'mime': 'image/png'}],
                symbol=self.agent.symbols[0],
                model=self.current_model
            )
            reply = result.get('reply', '이미지를 분석하는 데 문제가 생겼어요. 🙏')
            await update.message.reply_html(reply)
        except Exception as e:
            await update.message.reply_text(f"❌ 이미지 분석 중 오류: {str(e)}")

    # ── 외부 호출용 (비동기) ───────────────────────────────────

    async def _send_msg_async(self, text, parse_mode='HTML'):
        if not self.app or not self.chat_id: return
        await self.app.bot.send_message(chat_id=self.chat_id, text=text, parse_mode=parse_mode)

    def send_message(self, text, parse_mode='HTML'):
        """동기 인터페이스: 다른 스레드에서 호출 가능"""
        if self._loop and self.app and self.app.running:
            asyncio.run_coroutine_threadsafe(self._send_msg_async(text, parse_mode), self._loop)
        else:
            print(f"⚠️ 텔레그램 앱이 아직 실행 중이 아닙니다. 메시지 대기: {text[:20]}...")

    def send_trade_proposal(self, symbol, side, price, sl, tp, reasons):
        """거래 제안 알림 전송 (동기)"""
        dashboard_url = os.getenv('DASHBOARD_URL', 'http://localhost:9090')
        assistant_url = f"{dashboard_url}/trade-assistant"
        
        title = f"🎯 <b>아이린의 거래 제안</b> ({symbol})"
        action = "📈 LONG" if side == 'buy' else "📉 SHORT"
        
        msg = [
            title,
            f"\n방향: {action}",
            f"현재가: {price:,.2f}",
            f"손절가 (SL): {sl:,.2f}",
            f"익절가 (TP): {tp:,.2f}",
            "\n<b>핵심 분석:</b>",
        ]
        
        for r in reasons[:3]:
            msg.append(f"• {r}")
            
        msg.append(f"\n👉 <a href='{assistant_url}'>대시보드에서 승인하기</a>")
        
        self.send_message("\n".join(msg))

    def send_trade_execution_alert(self, symbol, side, qty, price, sl, tp, account='core'):
        """실제 주문 체결 알림 전송 (동기)"""
        acc_label = "🔵 코어(Core)" if account == 'core' else "🔴 위성(Shuttle)"
        title = f"🚀 <b>거래 진입 성공!</b> ({symbol})"
        action = "📈 LONG" if side.lower() == 'buy' else "📉 SHORT"
        
        msg = [
            title,
            f"\n계정: {acc_label}",
            f"방향: {action}",
            f"수량: {qty}",
            f"진입가: {price:,.2f}",
            f"손절가 (SL): {sl:,.2f}",
            f"익절가 (TP): {tp:,.2f}",
            f"\n아이린이 시장을 감시하며 대응할게요. 💎✨"
        ]
        
        self.send_message("\n".join(msg))

    # ── 실행 루프 ─────────────────────────────────────────────

    def run_polling(self):
        """별도 스레드에서 실행 — raw urllib 폴링 + asyncio 루프 상시 가동"""
        import urllib.request as _ur
        import json as _json
        print("🚀 아이린 텔레그램 봇 초기화 중...")

        # 웹훅 제거
        try:
            resp = _ur.urlopen(
                f'https://api.telegram.org/bot{self.token}/deleteWebhook',
                timeout=10
            )
            resp.read(); resp.close()
        except Exception:
            pass

        # asyncio 루프를 별도 스레드에서 run_forever()로 상시 가동
        self._loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        loop_thread = threading.Thread(target=_run_loop, daemon=True)
        loop_thread.start()

        # 루프가 뜰 때까지 잠깐 대기 후 PTB App 초기화
        time.sleep(0.5)

        async def _init_app():
            await self.app.initialize()
            await self.app.start()

        fut = asyncio.run_coroutine_threadsafe(_init_app(), self._loop)
        fut.result(timeout=30)  # 초기화 완료까지 대기

        print("🚀 아이린 텔레그램 봇 리스너 가동 (raw polling)...")

        offset = 0
        conflict_count = 0
        retry_delay = 5
        while True:
            try:
                url = (f'https://api.telegram.org/bot{self.token}/getUpdates'
                       f'?offset={offset}&timeout=30&limit=100&allowed_updates=message,callback_query')
                resp = _ur.urlopen(url, timeout=35)
                data = _json.loads(resp.read())
                resp.close()

                if data.get('ok'):
                    conflict_count = 0
                    retry_delay = 5
                    for upd in data.get('result', []):
                        offset = upd['update_id'] + 1
                        asyncio.run_coroutine_threadsafe(
                            self.app.process_update(
                                __import__('telegram').Update.de_json(upd, self.app.bot)
                            ),
                            self._loop
                        )
                else:
                    print(f"⚠️ 텔레그램 API 오류: {data}")
                    time.sleep(5)
            except _ur.HTTPError as e:
                if e.code == 409:
                    conflict_count += 1
                    if conflict_count == 1:
                        print("🚨 [충돌] 다른 봇 인스턴스가 실행 중입니다! 세션 경쟁 중...")
                    elif conflict_count % 6 == 0:
                        print(f"🚨 [충돌 {conflict_count}회] 아직 다른 인스턴스가 살아있습니다. 계속 대기...")
                    time.sleep(retry_delay)
                    retry_delay = min(60, retry_delay * 1.5)
                else:
                    print(f"⚠️ 폴링 HTTP 오류 {e.code}: {e.reason}")
                    time.sleep(5)
            except Exception as e:
                print(f"⚠️ 폴링 오류: {e}")
                time.sleep(5)

# 하위 호환성을 위한 래퍼 클래스
class TelegramNotifier(TelegramBot):
    pass
