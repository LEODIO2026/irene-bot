import os
import time
from dotenv import load_dotenv
from core.data_fetcher import DataFetcher

def test_api():
    print("🌸 아이린: 바이비트 API 연결 및 매매 기능 테스트를 시작할게요!")
    load_dotenv()
    
    fetcher = DataFetcher()
    exchange = fetcher.exchange
    symbol = os.getenv('CORE_SYMBOL', 'BTC/USDT')
    contract_symbol = symbol + ':USDT' if ':' not in symbol else symbol
    
    print("\n[1단계] 잔고 확인")
    balance = fetcher.fetch_balance()
    if balance is None or balance <= 0:
        print("⚠️ 아이린: 잔고가 부족해서 실제 주문 테스트는 무리예요. 지갑을 확인해주세요!")
        return
        
    print(f"\n[2단계] {symbol} 최소 수량(0.001) 시장가 매수(Buy) 진입 테스트")
    qty = 0.001
    leverage = 1
    
    try:
        # 레버리지 설정 (자율매매 로직과 동일하게 테스트) - contract symbol 사용
        exchange.set_leverage(leverage, contract_symbol)
        print(f"✅ 아이린: {symbol} 레버리지를 {leverage}배로 안전하게 맞췄어요.")
        
        # 롱(Buy) 포지션 진입 - contract symbol 사용
        buy_order = exchange.create_order(
            symbol=contract_symbol,
            type='market',
            side='buy',
            amount=qty
        )
        print(f"🚀 아이린: 매수 진입 성공! (주문 ID: {buy_order.get('id')})")
        
    except Exception as e:
        print(f"❌ 아이린: 매수 진입 중 문제가 발생했어요: {e}")
        return

    print("\n⏳ 포지션 유지 중... 5초 뒤에 바로 청산할게요. 두근두근...")
    time.sleep(5)
    
    print("\n[3단계] 포지션 청산 (시장가 매도)")
    try:
        # 숏(Sell) 방향으로 동일 수량 + reduceOnly 옵션을 주어 완전히 포지션 종료
        sell_order = exchange.create_order(
            symbol=contract_symbol,
            type='market',
            side='sell',
            amount=qty,
            params={'reduceOnly': True}
        )
        print(f"✨ 아이린: 청산 주문까지 완벽하게 성공! (주문 ID: {sell_order.get('id')})")
        print("\n🎉 아이린: 짝짝짝! 바이비트 API 연결과 매매 권한 모두 정상적으로 잘 작동하네요!")
    except Exception as e:
        print(f"❌ 아이린: 청산 주문 중 문제가 발생했어요! 앱을 켜서 수동으로 닫아주세요!: {e}")

if __name__ == "__main__":
    test_api()
