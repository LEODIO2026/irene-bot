"""
잔고 감시 스크립트
실행 후 잔고가 들어오면 자동으로 웹훅 테스트까지 실행해줘요!
"""
import ccxt
import time

env = {}
with open('.env') as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()

exchange = ccxt.bybit({
    'apiKey': env['BYBIT_API_KEY'],
    'secret': env['BYBIT_SECRET_KEY'],
    'enableRateLimit': True,
    'options': {'defaultType': 'linear'}
})
exchange.set_sandbox_mode(True)

print("아이린: 테스트넷 잔고 감시 시작! (10초마다 확인)")
print("잔고가 들어오면 자동으로 알려드릴게요 🔔\n")

attempt = 0
while True:
    attempt += 1
    try:
        balance = exchange.fetch_balance({'accountType': 'UNIFIED'})
        usdt_free = float(balance.get('USDT', {}).get('free', 0) or 0)
        usdt_total = float(balance.get('total', {}).get('USDT', 0) or 0)
        usdt = max(usdt_free, usdt_total)

        print(f"[{attempt:03d}회] USDT 잔고: {usdt:.2f}", end='\r')

        if usdt > 0:
            print(f"\n\n✅ 잔고 확인! USDT = {usdt:.2f}")
            print("아이린: 이제 웹훅 테스트를 진행하세요! 💪")
            print("\n터미널에서 아래 명령어 실행:")
            print(f"""
curl -X POST http://127.0.0.1:9090/webhook \\
  -H "Content-Type: application/json" \\
  -d '{{
    "passphrase": "irene_secret",
    "side": "buy",
    "symbol": "BTC/USDT",
    "sl": 69000,
    "tp": 75000
  }}'
""")
            break

    except Exception as e:
        print(f"\n[오류] {e}", end='\r')

    time.sleep(10)
