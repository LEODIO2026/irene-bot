import os
import time
import datetime
from dotenv import load_dotenv
from core.data_fetcher import DataFetcher
from execution.notion_logger import NotionLogger

load_dotenv()

def get_kst_timestamps(target_date):
    """target_date: datetime.date 객체"""
    # KST 기준 00:00:00 ~ 23:59:59
    # KST 00:00:00은 UTC 전날 15:00:00입니다.
    # KST 23:59:59는 UTC 당일 14:59:59입니다.
    
    start_dt_kst = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    end_dt_kst = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=datetime.timezone(datetime.timedelta(hours=9)))
    
    start_ts = int(start_dt_kst.timestamp() * 1000)
    end_ts = int(end_dt_kst.timestamp() * 1000)
    
    return start_ts, end_ts

def backfill_by_date(target_date_str=None):
    if target_date_str:
        target_date = datetime.datetime.strptime(target_date_str, "%Y-%m-%d").date()
    else:
        # 기본값은 어제
        target_date = datetime.date.today() - datetime.timedelta(days=1)
    
    print(f"🚀 아이린: {target_date} 거래 내역을 노션으로 동기화하는 중입니다...")
    
    start_ts, end_ts = get_kst_timestamps(target_date)
    
    fetcher = DataFetcher(label='코어')
    logger = NotionLogger()
    
    if not logger.is_configured():
        print("❌ 노션 설정이 되어 있지 않습니다. .env 파일을 확인해주세요.")
        return

    def fetch_all_in_range(f, s_ts, e_ts):
        all_items = []
        cursor = None
        while True:
            params = {
                'category': 'linear',
                'limit': 100,
                'startTime': s_ts,
                'endTime': e_ts
            }
            if cursor:
                params['cursor'] = cursor
            
            resp = f.exchange.privateGetV5PositionClosedPnl(params)
            items = resp.get('result', {}).get('list', [])
            if not items:
                break
            
            for item in items:
                all_items.append({
                    'symbol':      item.get('symbol', ''),
                    'side':        item.get('side', ''),
                    'qty':         float(item.get('qty') or 0),
                    'entry_price': float(item.get('avgEntryPrice') or 0),
                    'exit_price':  float(item.get('avgExitPrice') or 0),
                    'pnl':         round(float(item.get('closedPnl') or 0), 4),
                    'created_time': int(item.get('createdTime') or 0),
                })
            
            cursor = resp.get('result', {}).get('nextPageCursor')
            if not cursor:
                break
            time.sleep(0.2)
        return all_items

    # 1. 코어(메인) 계정 내역 가져오기
    print("🔍 코어 계정 거래 내역 조회 중...")
    main_history = fetch_all_in_range(fetcher, start_ts, end_ts)
    
    # 2. 위성 계정 내역 가져오기
    sat_api = os.getenv('SATELLITE_API_KEY')
    sat_history = []
    if sat_api and sat_api != os.getenv('BYBIT_API_KEY'):
        sat_fetcher = DataFetcher(
            api_key=sat_api,
            secret_key=os.getenv('SATELLITE_SECRET_KEY'),
            label='위성'
        )
        print("🔍 위성 계정 거래 내역 조회 중...")
        sat_history = fetch_all_in_range(sat_fetcher, start_ts, end_ts)

    all_trades = []
    for t in main_history:
        t['account'] = 'core'
        all_trades.append(t)
    for t in sat_history:
        t['account'] = 'satellite'
        all_trades.append(t)

    if not all_trades:
        print(f"ℹ️ {target_date}에 해당하는 거래 내역이 없습니다.")
        return

    print(f"📈 총 {len(all_trades)}건의 내역을 발견했습니다. 노션으로 전송을 시작합니다...")

    success_count = 0
    for trade in all_trades:
        symbol = trade['symbol']
        side = trade['side']
        entry_price = float(trade.get('entry_price', 0))
        exit_price = float(trade.get('exit_price', 0))
        pnl_usdt = float(trade.get('pnl', 0))
        close_time_ms = trade.get('created_time')
        
        # PnL % 계산
        pnl_pct = 0.0
        if entry_price > 0:
            if side.lower() in ['buy', 'long']:
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            else:
                pnl_pct = ((entry_price - exit_price) / entry_price) * 100

        # 전략 레이블 (기본값)
        strategy = "Manual" if trade['account'] == 'core' else "Satellite"
        
        # 노션 기록
        ok = logger.log_trade(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            pnl_usdt=pnl_usdt,
            strategy=strategy,
            close_time_ms=close_time_ms
        )
        
        if ok:
            success_count += 1
        
        # API 레이트 리밋 방지
        time.sleep(0.5)

    print(f"✨ 동기화 완료! (성공: {success_count}/{len(all_trades)})")

if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    backfill_by_date(date_arg)
