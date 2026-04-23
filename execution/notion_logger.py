import os
import requests
import datetime
from dotenv import load_dotenv

class NotionLogger:
    """
    아이린 매매 일지 — 노션(Notion) 연동 모듈
    종료된 거래(PnL 정산 완료) 내역을 노션 데이터베이스에 자동으로 기록합니다.
    """
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("NOTION_API_KEY")
        self.database_id = os.getenv("NOTION_DATABASE_ID")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }
        
    def is_configured(self):
        """노션 연동에 필요한 키와 DB ID가 모두 설정되어 있는지 확인합니다."""
        return bool(self.api_key and self.database_id)

    def log_trade(self, symbol: str, side: str, entry_price: float, exit_price: float, pnl_pct: float, pnl_usdt: float, close_time_ms: int = None):
        """
        노션 데이터베이스에 1줄의 매매 기록을 추가합니다.
        
        요구되는 노션 데이터베이스 속성(Property) 이름 및 타입:
        - Symbol (Title)
        - Side (Select)
        - Entry Price (Number)
        - Exit Price (Number)
        - PnL % (Number)
        - PnL USDT (Number)
        - Date (Date)
        """
        if not self.is_configured():
            return False

        try:
            # 시간 처리 (기본값은 현재 KST)
            try:
                from zoneinfo import ZoneInfo
                kst_tz = ZoneInfo("Asia/Seoul")
            except ImportError:
                from backports.zoneinfo import ZoneInfo
                kst_tz = ZoneInfo("Asia/Seoul")

            if close_time_ms:
                dt_utc = datetime.datetime.fromtimestamp(close_time_ms / 1000, datetime.timezone.utc)
                dt_kst = dt_utc.astimezone(kst_tz)
            else:
                dt_kst = datetime.datetime.now(kst_tz)
                
            iso_date = dt_kst.isoformat()

            # 노션 API 페이로드 구성
            data = {
                "parent": {"database_id": self.database_id},
                "properties": {
                    "Symbol": {
                        "title": [{"text": {"content": symbol}}]
                    },
                    "Side": {
                        "select": {"name": side.capitalize()}
                    },
                    "Entry Price": {
                        "number": round(float(entry_price), 4)
                    },
                    "Exit Price": {
                        "number": round(float(exit_price), 4)
                    },
                    "PnL %": {
                        "number": round(float(pnl_pct), 2)
                    },
                    "PnL USDT": {
                        "number": round(float(pnl_usdt), 2)
                    },
                    "Date": {
                        "date": {"start": iso_date}
                    }
                }
            }

            url = "https://api.notion.com/v1/pages"
            response = requests.post(url, headers=self.headers, json=data, timeout=10)

            if response.status_code in [200, 201]:
                print(f"✅ 아이린: 노션 매매 일지 기록 성공 ({symbol} {side.upper()})")
                return True
            else:
                print(f"⚠️ 아이린: 노션 기록 실패 - 상태코드: {response.status_code}, 메시지: {response.text}")
                return False

        except Exception as e:
            print(f"⚠️ 아이린: 노션 로깅 중 예외 발생: {e}")
            return False

if __name__ == "__main__":
    # 단독 테스트
    print("─── 아이린 v3: 노션 로거 테스트 ───")
    logger = NotionLogger()
    if not logger.is_configured():
        print("설정 안 됨: .env 파일에 NOTION_API_KEY와 NOTION_DATABASE_ID를 확인하세요.")
    else:
        print("연동 시도 중...")
        # 가상의 데이터로 테스트
        success = logger.log_trade(
            symbol="BTCUSDT",
            side="Long",
            entry_price=60000.5,
            exit_price=61200.0,
            pnl_pct=2.0,
            pnl_usdt=15.5
        )
        if success:
            print("성공적으로 노션에 데이터가 입력되었습니다!")
