import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

class TelegramNotifier:
    def __init__(self, token=None, chat_id=None):
        self.token = token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text, parse_mode='HTML'):
        if not self.token or not self.chat_id:
            print("⚠️ 텔레그램 설정이 완료되지 않았습니다. (TOKEN 또는 CHAT_ID 누락)")
            return False
        
        url = f"{self.base_url}/sendMessage"
        payload = {
            'chat_id': self.chat_id,
            'text': text,
            'parse_mode': parse_mode,
            'disable_web_page_preview': False
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            if result.get('ok'):
                return True
            else:
                print(f"❌ 텔레그램 전송 실패: {result.get('description')}")
                return False
        except Exception as e:
            print(f"❌ 텔레그램 전송 중 오류 발생: {e}")
            return False

    def send_trade_proposal(self, symbol, side, price, sl, tp, reasons):
        """거래 제안 알림 전송"""
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
        
        for r in reasons[:3]:  # 주요 사유 3개만
            msg.append(f"• {r}")
            
        msg.append(f"\n👉 <a href='{assistant_url}'>아이린 어시스턴트에서 확인 및 승인하기</a>")
        
        return self.send_message("\n".join(msg))

if __name__ == "__main__":
    # 테스트 코드
    notifier = TelegramNotifier()
    notifier.send_message("테스트 메시지입니다! 아이린이 잘 작동하나요? 😊")
