import os
import time
from dotenv import load_dotenv
from core.data_fetcher import DataFetcher
from core.ict_engine import ICTEngine
from analysis.sentiment_analyzer import SentimentAnalyzer

load_dotenv()

def generate_live_report():
    symbol = os.getenv('CORE_SYMBOL', 'BTC/USDT')
    fetcher = DataFetcher()  # .env의 USE_TESTNET 설정을 자동으로 따름
    engine = ICTEngine()
    analyzer = SentimentAnalyzer()
    
    print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 아이린: 실시간 바이비트 시장 분석 리포트 제작 중...")
    
    # 1. 데이터 수집
    data = fetcher.fetch_top_down_data(symbol)
    if not data:
        print("아이린: 데이터 수집에 실패했습니다. 전원을 다시 껐다 켜야 할 것 같군요.")
        return

    # 2. 분석
    h1_data = data.get('1h')
    m15_data = data.get('15m')
    
    mss_h1 = engine.detect_mss(h1_data)
    fvgs_h1 = engine.detect_fvg(h1_data)
    sweeps_m15 = engine.detect_liquidity_sweeps(m15_data)
    
    # 3. 심리 데이터 (모의값 혹은 API 연동)
    funding = fetcher.fetch_funding_rate(symbol) or 0.0001
    ls_ratio = 1.2 # 실제 API 호출 시 fetcher에서 연동 가능
    score = analyzer.calculate_sentiment_score(ls_ratio, funding, 0)
    status, market_msg = analyzer.evaluate_market_condition(score)

    # 4. 리포트 출력
    print("-" * 50)
    print(f"아이린 분석 결과: {symbol}")
    print(f"- 시장 심리: {status}")
    print(f"- 소견: {market_msg}")
    print("-" * 50)
    
    if mss_h1:
        print(f"아이린: 1시간 봉 기준 시장 구조 변화(MSS) 감지! 유의미한 변동성 구간입니다.")
    if fvgs_h1:
        print(f"아이린: 현재 상위 타임프레임에 {len(fvgs_h1)}개의 불균형(FVG) 구간이 존재합니다. 되돌림 타점을 노릴 수 있습니다.")
    if sweeps_m15:
        print(f"아이린: 최근 15분 봉에서 유동성 사냥(Sweep) 포인트가 발견되었습니다. {sweeps_m15[-1]['type']}에 주목하세요.")
    
    if not mss_h1 and not fvgs_h1 and not sweeps_m15:
        print("아이린: 현재 유의미한 ICT 셋업이 발견되지 않았습니다. 이런 날엔 우아하게 샴페인이나 마시는 게 낫겠군요. 관망합니다.")
    print("-" * 50 + "\n")

if __name__ == "__main__":
    generate_live_report()
