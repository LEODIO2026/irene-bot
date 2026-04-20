import os
import json
from dotenv import load_dotenv
from core.data_fetcher import DataFetcher

load_dotenv()

def get_history():
    print("아이린: 거래소 데이터베이스에서 직접 거래 내역을 수집하는 중입니다... 🔍")
    
    # 1. 메인 계정 수집
    main_fetcher = DataFetcher(label='메인')
    main_pnl = main_fetcher.fetch_closed_pnl(limit=20)
    
    # 2. 위성 계정 수집 (API 키가 다를 경우에만 따로 시도)
    sat_api = os.getenv('SATELLITE_API_KEY')
    satellite_pnl = []
    if sat_api and sat_api != os.getenv('BYBIT_API_KEY'):
        sat_fetcher = DataFetcher(
            api_key=sat_api,
            secret_key=os.getenv('SATELLITE_SECRET_KEY'),
            label='위성'
        )
        satellite_pnl = sat_fetcher.fetch_closed_pnl(limit=20)
    
    history = {
        'main': main_pnl,
        'satellite': satellite_pnl,
        'trading_paused': os.getenv('TRADING_PAUSED', 'False').lower() == 'true',
        'trading_mode': os.getenv('TRADING_MODE', 'autonomous')
    }
    
    print(f"아이린: 수집 완료! (메인: {len(main_pnl)}건, 위성: {len(satellite_pnl)}건)")
    print(json.dumps(history, indent=2))

if __name__ == "__main__":
    get_history()
