import os
from dotenv import load_dotenv

load_dotenv()

class Executor:
    def __init__(self, exchange_client):
        self.exchange = exchange_client

    def place_order(self, symbol, side, qty, leverage, stop_loss=None, take_profit=None):
        """
        실제 거래소(Bybit)에 주문을 제출합니다.
        """
        try:
            # 1. 심볼 변환 (Bybit V5 Linear는 BTC/USDT:USDT 형태 필요)
            contract_symbol = symbol
            if ':' not in contract_symbol:
                quote = contract_symbol.split('/')[1]
                contract_symbol = f"{contract_symbol}:{quote}"

            # 2. 레버리지 설정
            self.exchange.set_leverage(leverage, contract_symbol)
            print(f"아이린: 바이비트 레버리지를 {leverage}배로 셋팅했습니다. ({symbol})")
            
            # 3. 메인 주문 실행
            params = {}
            if stop_loss:
                params['stopLoss'] = str(stop_loss)
            if take_profit:
                params['takeProfit'] = str(take_profit)
                
            order = self.exchange.create_order(
                symbol=contract_symbol,
                type='market',
                side=side,
                amount=qty,
                params=params
            )
            print(f"아이린: {symbol} {side.upper()} 진입 성공. (Bybit ID: {order['id']})")
            
            return order
        except Exception as e:
            print(f"아이린: 바이비트 주문 중 오류 발생 ({symbol}): {e}")
            return None

    def set_trading_stop(self, symbol, stop_loss=None, take_profit=None):
        """
        열린 포지션의 SL/TP를 변경합니다. (피라미딩 후 SL → BE 이동에 사용)
        Bybit V5 /v5/position/trading-stop 엔드포인트 사용.
        """
        try:
            contract_symbol = symbol
            if ':' not in contract_symbol:
                quote = contract_symbol.split('/')[1]
                contract_symbol = f"{contract_symbol}:{quote}"
            bybit_symbol = contract_symbol.replace('/USDT:USDT', 'USDT').replace('/', '')

            params = {
                'category': 'linear',
                'symbol':   bybit_symbol,
                'positionIdx': 0,  # one-way mode
            }
            if stop_loss:
                params['stopLoss']    = str(stop_loss)
                params['slTriggerBy'] = 'MarkPrice'
            if take_profit:
                params['takeProfit']  = str(take_profit)
                params['tpTriggerBy'] = 'MarkPrice'

            result = self.exchange.privatePostV5PositionTradingStop(params)
            print(f"아이린: [{symbol}] SL→{stop_loss} 수정 완료")
            return result
        except Exception as e:
            print(f"아이린: SL/TP 수정 오류 ({symbol}): {e}")
            return None

    def get_position_status(self, symbol):
        """
        현재 열려 있는 포지션 상태를 조회합니다.
        Bybit V5는 'BTC/USDT:USDT' 형식의 contract symbol이 필요합니다.
        """
        try:
            # BTC/USDT → BTC/USDT:USDT 변환
            contract_symbol = symbol
            if ':' not in contract_symbol:
                quote = contract_symbol.split('/')[1]
                contract_symbol = f"{contract_symbol}:{quote}"
            positions = self.exchange.fetch_positions([contract_symbol])
            return positions
        except Exception as e:
            print(f"아이린: 포지션 조회 오류 ({symbol}): {e}")
            return None
