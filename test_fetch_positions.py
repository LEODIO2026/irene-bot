import ccxt
import os
from dotenv import load_dotenv
load_dotenv()
exchange = ccxt.bybit({
    'apiKey': os.getenv('BYBIT_API_KEY'),
    'secret': os.getenv('BYBIT_SECRET_KEY'),
    'options': {'defaultType': 'linear'}
})
for sym in ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT']:
    try:
        pos = exchange.fetch_positions([sym])
        print(f"Success: {sym}")
    except Exception as e:
        print(f"Error: {sym} -> {e}")
