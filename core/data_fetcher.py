import ccxt
import pandas as pd
import time
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

class DataFetcher:
    def __init__(self, use_testnet=None, api_key=None, secret_key=None, label='메인'):
        """
        Args:
            use_testnet : None이면 .env USE_TESTNET 기준
            api_key     : 명시적으로 넘기면 .env 무시 (서브계정 지원)
            secret_key  : 명시적으로 넘기면 .env 무시 (서브계정 지원)
            label       : 로그 식별용 ('메인' | '위성' 등)
        """
        if use_testnet is None:
            use_testnet = os.getenv('USE_TESTNET', 'True').strip().split('#')[0].strip().lower() == 'true'
        self.api_key    = api_key    or os.getenv('BYBIT_API_KEY')
        self.secret_key = secret_key or os.getenv('BYBIT_SECRET_KEY')
        self.label      = label

        self.exchange = ccxt.bybit({
            'apiKey': self.api_key,
            'secret': self.secret_key,
            'enableRateLimit': True,
            'timeout': 30000,
            'options': {
                'defaultType': 'linear'
            }
        })

        if use_testnet:
            self.exchange.set_sandbox_mode(True)
            print(f"아이린[{self.label}]: 바이비트 TESTNET 모드.")
        else:
            print(f"아이린[{self.label}]: 바이비트 MAINNET 모드. 긴장하십시오.")

    def fetch_ohlcv(self, symbol, timeframe='1h', limit=500):
        """
        특정 심볼과 타임프레임의 OHLCV 데이터를 가져와 Pandas DataFrame으로 반환합니다.
        페이지네이션을 지원하여 limit이 1000개를 초과할 경우 여러 번 나눠서 가져옵니다.
        """
        try:
            contract_symbol = self._to_contract_symbol(symbol)
            all_ohlcv = []
            
            # 타임프레임별 밀리초 계산
            tf_ms = self.exchange.parse_timeframe(timeframe) * 1000
            
            # 수집할 시작 시점 계산 (대략적인 추정)
            now = self.exchange.milliseconds()
            since = now - (limit * tf_ms)
            
            remaining_limit = limit
            while remaining_limit > 0:
                fetch_limit = min(remaining_limit, 1000)
                ohlcv = self.exchange.fetch_ohlcv(contract_symbol, timeframe, since=since, limit=fetch_limit)
                
                if not ohlcv:
                    break
                
                all_ohlcv.extend(ohlcv)
                remaining_limit -= len(ohlcv)
                
                # 다음 조회를 위해 since 업데이트 (마지막 봉의 시간 + 1차시)
                since = ohlcv[-1][0] + tf_ms
                
                # 과도한 API 호출 방지 및 중복 체크
                if len(ohlcv) < fetch_limit: # 더 이상 데이터 없음
                    break
                
                # 속도 제한 준수
                time.sleep(self.exchange.rateLimit / 1000)

            if not all_ohlcv:
                return None

            # 중복 제거 및 정렬
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # 최종 요청한 limit 만큼 자르기 (가장 최근 데이터 기준)
            return df.tail(limit)

        except Exception as e:
            print(f"아이린: 데이터 수집 중 오류 발생 ({symbol}, {timeframe}): {e}")
            return None

    def fetch_top_down_data(self, symbol, timeframes=['1d', '4h', '15m', '5m'], limits={'1d': 100, '4h': 100, '15m': 100, '5m': 100}):
        """
        여러 타임프레임의 데이터를 한꺼번에 수집합니다.
        """
        data = {}
        for tf in timeframes:
            limit = limits.get(tf, 100)
            df = self.fetch_ohlcv(symbol, tf, limit=limit)
            if df is not None:
                data[tf] = df
            time.sleep(self.exchange.rateLimit / 1000)  # Rate limit 준수
        return data

    @staticmethod
    def _to_contract_symbol(symbol):
        """
        'BTC/USDT' 형식을 선물 API에 필요한 'BTC/USDT:USDT' 형식으로 자동 변환합니다.
        이미 ':' 가 포함된 심볼은 그대로 반환합니다.
        """
        if ':' not in symbol:
            # BTC/USDT -> BTC/USDT:USDT (결제 통화 추출)
            quote = symbol.split('/')[1]  # USDT
            return f"{symbol}:{quote}"
        return symbol

    def fetch_funding_rate(self, symbol):
        """
        현재 펀딩비 데이터를 가져옵니다.
        """
        try:
            contract_symbol = self._to_contract_symbol(symbol)
            funding = self.exchange.fetch_funding_rate(contract_symbol)
            return funding['fundingRate']
        except Exception as e:
            print(f"아이린: 펀딩비 조회 오류: {e}")
            return None

    def fetch_open_interest(self, symbol):
        """
        현재 미결제약정(Open Interest) 데이터를 가져옵니다.
        """
        try:
            contract_symbol = self._to_contract_symbol(symbol)
            oi = self.exchange.fetch_open_interest(contract_symbol)
            return float(oi['openInterestAmount'])
        except Exception as e:
            print(f"아이린: 미결제약정 조회 오류: {e}")
            return None

    def fetch_long_short_ratio(self, symbol, period='1h'):
        """
        바이비트 V5 API에서 롱/숏 비율을 가져옵니다. (계정 비율 기준)
        """
        try:
            bybit_symbol = symbol.replace('/', '').replace(':USDT', '')
            params = {
                'category': 'linear',
                'symbol': bybit_symbol,
                'period': period,
                'limit': 1
            }
            # CCXT의 전용 메서드가 없을 경우 세이프하게 publicGetV5MarketAccountRatio 사용
            response = self.exchange.public_get_v5_market_account_ratio(params)
            if response.get('retCode') == 0 and response.get('result', {}).get('list'):
                item = response['result']['list'][0]
                buy_ratio = float(item.get('buyRatio', 0.5))
                sell_ratio = float(item.get('sellRatio', 0.5))
                return buy_ratio / sell_ratio if sell_ratio > 0 else 1.0
            return 1.0
        except Exception as e:
            print(f"아이린: 롱/숏 비율 조회 오류: {e}")
            return 1.0

    def fetch_oi_history(self, symbol, interval='1h', limit=24):
        """
        미결제약정 히스토리를 가져옵니다.
        """
        try:
            bybit_symbol = symbol.replace('/', '').replace(':USDT', '')
            params = {
                'category': 'linear',
                'symbol': bybit_symbol,
                'intervalTime': interval,
                'limit': limit
            }
            response = self.exchange.public_get_v5_market_open_interest(params)
            if response.get('retCode') == 0 and response.get('result', {}).get('list'):
                result = []
                for item in response['result']['list']:
                    result.append({
                        'ts': int(item.get('timestamp', 0)),
                        'oi': float(item.get('openInterest', 0))
                    })
                result.reverse()  # 시간순 정렬
                return result
            return []
        except Exception as e:
            print(f"아이린: OI 히스토리 조회 오류: {e}")
            return []

    def fetch_oi_change_rate(self, symbol, interval='1h', lookback=6):
        """
        미결제약정(OI)의 변화율을 계산합니다.
        
        Returns:
            dict: {
                'oi_current': float,     # 현재 OI
                'oi_change_pct': float,  # lookback 단위 대비 % 변화
                'trend': str,            # 'rising' | 'falling' | 'neutral'
                'signal': str,           # 'bullish_confirm' | 'bearish_confirm' | 'reversal_risk' | 'neutral'
            }
        """
        try:
            history = self.fetch_oi_history(symbol, interval=interval, limit=lookback + 1)
            if len(history) < 2:
                return {'oi_current': 0, 'oi_change_pct': 0, 'trend': 'neutral', 'signal': 'neutral'}

            oi_now  = history[-1]['oi']
            oi_prev = history[0]['oi']
            change_pct = (oi_now - oi_prev) / oi_prev * 100 if oi_prev > 0 else 0

            if change_pct > 2.0:
                trend = 'rising'
            elif change_pct < -2.0:
                trend = 'falling'
            else:
                trend = 'neutral'

            return {
                'oi_current': round(oi_now, 0),
                'oi_change_pct': round(change_pct, 2),
                'trend': trend,
                'signal': trend  # 상위 레이어에서 가격 방향과 조합하여 해석
            }
        except Exception as e:
            print(f"아이린: OI 변화율 계산 오류: {e}")
            return {'oi_current': 0, 'oi_change_pct': 0, 'trend': 'neutral', 'signal': 'neutral'}

    def fetch_long_short_history(self, symbol, period='1h', limit=6):
        """
        롤/숯 비율 히스토리 (최신 limit개) 를 가져옵니다.
        
        Returns:
            dict: {
                'current_ratio': float,    # 현재 롤/숯 비율
                'avg_ratio': float,        # 평균 비율
                'bias': str,               # 'long_heavy' | 'short_heavy' | 'neutral'
            }
        """
        try:
            bybit_symbol = symbol.replace('/', '').replace(':USDT', '')
            params = {
                'category': 'linear',
                'symbol': bybit_symbol,
                'period': period,
                'limit': limit
            }
            response = self.exchange.public_get_v5_market_account_ratio(params)
            if response.get('retCode') == 0 and response.get('result', {}).get('list'):
                items = response['result']['list']
                ratios = []
                for item in items:
                    buy  = float(item.get('buyRatio', 0.5))
                    sell = float(item.get('sellRatio', 0.5))
                    ratios.append(buy / sell if sell > 0 else 1.0)
                
                current = ratios[0]  # 가장 최신
                avg     = sum(ratios) / len(ratios)
                
                if current > 1.5:
                    bias = 'long_heavy'
                elif current < 0.67:
                    bias = 'short_heavy'
                else:
                    bias = 'neutral'
                
                return {'current_ratio': round(current, 3), 'avg_ratio': round(avg, 3), 'bias': bias}
            return {'current_ratio': 1.0, 'avg_ratio': 1.0, 'bias': 'neutral'}
        except Exception as e:
            print(f"아이린: 롤숯 히스토리 조회 오류: {e}")
            return {'current_ratio': 1.0, 'avg_ratio': 1.0, 'bias': 'neutral'}

    def fetch_balance(self, currency='USDT'):
        """
        거래소(Bybit)에서 현재 사용 가능한 잔고를 가져옵니다.
        """
        try:
            balance_info = self.exchange.fetch_balance({'accountType': 'UNIFIED'})
            free = balance_info.get(currency, {}).get('free', None)
            if free is not None and float(free) > 0:
                return float(free)
            total = balance_info.get('total', {}).get(currency, None)
            if total is not None and float(total) > 0:
                return float(total)
            return None
        except Exception as e:
            print(f"아이린: 잔고 조회 오류: {e}")
            return None

    def fetch_positions(self, symbols=None):
        """
        현재 열린 포지션 목록을 가져옵니다.
        """
        try:
            all_positions = self.exchange.fetch_positions()
            result = {}
            for pos in all_positions:
                size = float(pos.get('contracts', 0) or 0)
                if size == 0:
                    continue
                sym = pos.get('symbol', '')
                normalized = sym.split(':')[0] if ':' in sym else sym
                if symbols and normalized not in symbols:
                    continue
                result[normalized] = {
                    'side':           pos.get('side', ''),
                    'size':           size,
                    'entry_price':    float(pos.get('entryPrice') or 0),
                    'unrealized_pnl': round(float(pos.get('unrealizedPnl') or 0), 4),
                    'percentage':     round(float(pos.get('percentage') or 0), 2),
                    'liq_price':      float(pos.get('liquidationPrice') or 0),
                    'leverage':       float(pos.get('leverage') or 1),
                    'notional':       round(float(pos.get('notional') or 0), 2),
                }
            return result
        except Exception as e:
            print(f"아이린: 포지션 조회 오류: {e}")
            return {}

    def fetch_closed_pnl(self, symbol=None, limit=50):
        """
        Bybit closed-pnl 엔드포인트로 최근 실현 손익 목록 반환.
        Returns list of dicts: symbol, side, qty, entry_price, exit_price, pnl, created_time
        """
        try:
            params = {'category': 'linear', 'limit': limit}
            if symbol:
                params['symbol'] = symbol.replace('/USDT:USDT','USDT').replace('/USDT','USDT').replace('/','')
            resp = self.exchange.privateGetV5PositionClosedPnl(params)
            items = resp.get('result', {}).get('list', [])
            result = []
            for item in items:
                result.append({
                    'symbol':      item.get('symbol', ''),
                    'side':        item.get('side', ''),
                    'qty':         float(item.get('qty') or 0),
                    'entry_price': float(item.get('avgEntryPrice') or 0),
                    'exit_price':  float(item.get('avgExitPrice') or 0),
                    'pnl':         round(float(item.get('closedPnl') or 0), 4),
                    'created_time': int(item.get('createdTime') or 0),  # ms timestamp
                })
            return result
        except Exception as e:
            print(f"아이린: closed PnL 조회 오류: {e}")
            return []

if __name__ == "__main__":
    fetcher = DataFetcher()
    symbol = 'BTC/USDT'
    data = fetcher.fetch_top_down_data(symbol)
    if data:
        print(f"아이린: {symbol} 데이터 로드 완료")
        print(f"OI: {fetcher.fetch_open_interest(symbol)}")
        print(f"LS Ratio: {fetcher.fetch_long_short_ratio(symbol)}")
