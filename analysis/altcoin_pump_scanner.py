import time
import pandas as pd
from datetime import datetime
from core.data_fetcher import DataFetcher
from analysis.whale_detector import WhaleManipulationDetector
from analysis.smart_money_tracker import SmartMoneyTracker
from execution.notifier import TelegramNotifier

class AltcoinPumpScanner:
    def __init__(self, fetcher=None, notifier=None):
        self.fetcher = fetcher or DataFetcher(label='Scanner')
        self.notifier = notifier or TelegramNotifier()
        self.whale_detector = WhaleManipulationDetector(fetcher=self.fetcher)
        self.smart_money = SmartMoneyTracker(fetcher=self.fetcher)
        
        # 설정
        self.scan_interval = 15 * 60  # 15분마다 전체 스캔
        self.top_n = 50  # 거래량 상위 N개만 검사
        self.funding_threshold = -0.0010  # 펀딩비 -0.10% 이하 (극단적 숏)
        
        # 중복 알림 방지 캐시 {symbol: timestamp}
        self.alert_cache = {}

    def fetch_top_altcoins(self):
        """거래량 기준 상위 알트코인 심볼 리스트를 반환합니다."""
        try:
            # 바이비트 v5 linear 전체 티커 조회
            response = self.fetcher.exchange.public_get_v5_market_tickers({'category': 'linear'})
            if not response or response.get('retCode') != 0:
                return []
                
            tickers = response['result']['list']
            # USDT 페어만 필터링하고 BTC, ETH는 제외 (알트코인 목적)
            alts = [
                t for t in tickers 
                if t['symbol'].endswith('USDT') 
                and t['symbol'] not in ['BTCUSDT', 'ETHUSDT']
            ]
            
            # 거래량(turnover24h) 기준으로 내림차순 정렬
            alts.sort(key=lambda x: float(x.get('turnover24h', 0)), reverse=True)
            
            # 상위 top_n개 심볼 추출 (API 형식에 맞게 변환)
            top_symbols = []
            for t in alts[:self.top_n]:
                sym = t['symbol']
                # BTCUSDT -> BTC/USDT 형식으로 변환 (DataFetcher 호환)
                base = sym[:-4]
                quote = sym[-4:]
                top_symbols.append(f"{base}/{quote}")
                
            return top_symbols
        except Exception as e:
            print(f"아이린: 티커 목록 조회 중 오류 발생: {e}")
            return []

    def scan_market(self):
        """전체 알트코인 시장을 스캔하여 전조 증상을 포착합니다."""
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 🐙 알트코인 폭등 전조 스캐너 가동 중...")
        
        symbols = self.fetch_top_altcoins()
        if not symbols:
            return

        for symbol in symbols:
            try:
                score = 0.0
                reasons = []
                
                # ── 1. 펀딩비 극단적 마이너스 체크 (숏 스퀴즈 전조) ──
                funding_rate = self.fetcher.fetch_funding_rate(symbol)
                if funding_rate is not None and funding_rate <= self.funding_threshold:
                    score += 5.0
                    reasons.append(f"🔥 극단적 펀딩비({funding_rate*100:.3f}%): 숏 스퀴즈 위험(펌핑 가능성)")

                # ── 2. 거래량 및 매집 패턴 체크 ──
                # 15분 봉 데이터 가져오기 (가장 최근 50개)
                df_15m = self.fetcher.fetch_ohlcv(symbol, '15m', limit=50)
                if df_15m is not None and len(df_15m) > 20:
                    # 거래량 이상 감지 (최근 3개 캔들 내에서)
                    anomalies = self.whale_detector.detect_volume_anomaly(df_15m, lookback=20, threshold=3.0)
                    recent_anom = [a for a in anomalies if a['index'] >= len(df_15m) - 3]
                    
                    if recent_anom:
                        latest = recent_anom[-1]
                        if latest['direction'] == 'bullish':
                            score += 3.0
                            reasons.append(f"📢 폭발적 매수 거래량 포착 (평균의 {latest['vol_ratio']}배!)")

                    # 흡수(Absorption) 패턴 체크 (세력 매집)
                    absorptions = self.whale_detector.detect_absorption(df_15m)
                    recent_abs = [a for a in absorptions if a['index'] >= len(df_15m) - 3]
                    if recent_abs:
                        latest_abs = recent_abs[-1]
                        if 'bullish' in latest_abs['type']:
                            score += 2.0
                            reasons.append(f"💎 세력 매집(Absorption) 흔적 포착 (꼬리 비율 {latest_abs['wick_ratio']:.0%})")
                
                # ── 3. 미결제약정(OI) 급변 체크 ──
                oi_data = self.fetcher.fetch_oi_change_rate(symbol, interval='15m', lookback=4)
                if oi_data and oi_data['trend'] == 'rising' and oi_data['oi_change_pct'] >= 5.0:
                    score += 2.0
                    reasons.append(f"📈 미결제약정(OI) {oi_data['oi_change_pct']:.1f}% 급등: 새로운 돈 유입!")

                # ── 알림 전송 로직 ──
                # 총점이 5점 이상이면 텔레그램 알림 발송
                if score >= 5.0:
                    self._send_alert(symbol, score, reasons)
                    
                # API 제한을 피하기 위해 잠시 대기
                time.sleep(0.5)

            except Exception as e:
                print(f"아이린: {symbol} 스캔 중 오류: {e}")
                
        print(f"✅ 스캔 완료! (대상: 상위 {len(symbols)}개 코인)")

    def _send_alert(self, symbol, score, reasons):
        """텔레그램으로 탐지 알림을 전송합니다."""
        now = time.time()
        # 같은 코인은 1시간(3600초) 이내에 중복 알림 방지
        if symbol in self.alert_cache and (now - self.alert_cache[symbol]) < 3600:
            return
            
        self.alert_cache[symbol] = now
        
        msg = [
            f"🚨 <b>아이린 레이더 발동! 폭등 전조 포착</b> 🚨",
            f"<b>종목</b>: #{symbol.replace('/', '')}",
            f"<b>위험도/신뢰도 점수</b>: {score}점",
            f"\n<b>[포착된 세력의 흔적]</b>"
        ]
        
        for r in reasons:
            msg.append(f"• {r}")
            
        msg.append(f"\n⚠️ <i>변동성이 매우 큽니다. 스캘핑 시 칼손절 필수!</i>")
        
        # 텔레그램 전송
        self.notifier.send_message("\n".join(msg))
        print(f"🔔 텔레그램 알림 발송 완료: {symbol}")

    def run_forever(self):
        """백그라운드에서 주기적으로 스캔을 실행합니다."""
        # 봇이 시작되고 텔레그램 연결을 기다림
        time.sleep(10)
        while True:
            try:
                self.scan_market()
            except Exception as e:
                print(f"아이린: 스캐너 전체 루프 오류: {e}")
            time.sleep(self.scan_interval)

if __name__ == "__main__":
    scanner = AltcoinPumpScanner()
    scanner.scan_market()
