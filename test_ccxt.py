import ccxt
exchange = ccxt.bybit({'options': {'defaultType': 'linear'}})
for sym in ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']:
    try:
        data = exchange.fetch_ohlcv(sym, '1m', limit=2)
        print(f"Success: {sym} -> length {len(data)}, price {data[-1][4]}")
    except Exception as e:
        print(f"Error: {sym} -> {e}")
