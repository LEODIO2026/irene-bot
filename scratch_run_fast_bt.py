import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.backtester import Backtester

def run_fast():
    bt = Backtester(symbol='BTC/USDT', initial_balance=1000)
    # 5000 캔들이면 약 50일 분량의 15분봉 데이터입니다. (충분한 검증 기간이면서 빠릅니다)
    bt.run(limit=5000)

if __name__ == '__main__':
    run_fast()
