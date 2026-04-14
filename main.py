import os
import time
import threading
from dotenv import load_dotenv
from core.data_fetcher import DataFetcher
from core.ict_engine import ICTEngine
from core.decision_maker import DecisionMaker
from analysis.crowd_psychology import CrowdPsychologyEngine
from analysis.smart_money_tracker import SmartMoneyTracker
from analysis.whale_detector import WhaleManipulationDetector
from analysis.macro_news_sensor import MacroNewsSensor
from execution.risk_manager import RiskManager
from execution.executor import Executor
from execution.tv_bridge import TVBridge
from strategy.satellite import SatelliteStrategy
from strategy.barbell_manager import BarbellManager

load_dotenv()

class IreneAgent:
    def __init__(self):
        # ── 여러 종목 지원 (콤마로 구분) ──
        symbols_str = os.getenv('CORE_SYMBOLS', 'BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,BNB/USDT')
        self.symbols = [s.strip() for s in symbols_str.split(',') if s.strip()]
        self.use_testnet = os.getenv('USE_TESTNET', 'True') == 'True'
        self.trading_paused = os.getenv('TRADING_PAUSED', 'False') == 'True'  # 🛑 매매 일시 중단 플래그
        if self.trading_paused:
            print("⛔ 아이린: TRADING_PAUSED=True → 분석만 수행, 실제 주문은 차단됩니다.")
        
        # ── 코어 (메인계정) ──
        self.fetcher      = DataFetcher(use_testnet=self.use_testnet, label='코어')
        self.ict_engine   = ICTEngine()
        self.risk_manager = RiskManager(risk_per_trade=float(os.getenv('RISK_PER_TRADE', 0.02)))
        self.executor     = Executor(self.fetcher.exchange)

        # ── 위성 (서브계정) — API 키가 없으면 메인계정 공유 ──
        sat_api_key    = os.getenv('SATELLITE_API_KEY')
        sat_secret_key = os.getenv('SATELLITE_SECRET_KEY')
        if sat_api_key and sat_secret_key:
            self.satellite_fetcher  = DataFetcher(
                use_testnet=self.use_testnet,
                api_key=sat_api_key,
                secret_key=sat_secret_key,
                label='위성',
            )
            self.satellite_executor = Executor(self.satellite_fetcher.exchange)
            print("🔴 위성 서브계정 연결 완료 (독립 API 키)")
        else:
            # 서브계정 키 미설정 시 메인계정으로 fallback (경고 출력)
            self.satellite_fetcher  = self.fetcher
            self.satellite_executor = self.executor
            print("⚠️  위성 서브계정 키 미설정 → 메인계정으로 동작 (SATELLITE_API_KEY 권장)")
        
        # ── v3 신급 모듈 초기화 ──
        self.crowd_engine = CrowdPsychologyEngine(fetcher=self.fetcher)
        self.smart_money = SmartMoneyTracker(fetcher=self.fetcher)
        self.whale_detector = WhaleManipulationDetector(fetcher=self.fetcher)  # ✨ 실시간 OI 연동
        self.news_sensor = MacroNewsSensor()
        
        # ── 두뇌 (자율 매매 판단 엔진) v4.2 ──
        self.decision_maker = DecisionMaker(
            ict_engine=self.ict_engine,
            min_confluence=4.7,
            cooldown_minutes=30,
            enable_ltf_scalp=True,
            ltf_scalp_min_confluence=3.5,
            scalp_cooldown_minutes=90,
            crowd_engine=self.crowd_engine,
            smart_money=self.smart_money,
            whale_detector=self.whale_detector,
            news_sensor=self.news_sensor
        )

        # ── 바벨 전략: 위성(공격) 모듈 ──
        satellite_capital = float(os.getenv('SATELLITE_CAPITAL', 467.0))
        total_capital     = float(os.getenv('TOTAL_CAPITAL', 1556.0))
        self.satellite = SatelliteStrategy(
            ict_engine=self.ict_engine,
            satellite_capital=satellite_capital,
            base_risk_pct=float(os.getenv('SATELLITE_RISK_PCT', 0.08)),    # 최공격: 8%
            max_leverage=int(os.getenv('SATELLITE_MAX_LEV', 20)),
            compound_win_factor=float(os.getenv('SATELLITE_COMPOUND_WIN', 1.5)),
            max_compound_factor=float(os.getenv('SATELLITE_MAX_COMPOUND', 5.0)),
            min_rr=3.0,
        )
        self.barbell = BarbellManager(
            core_decision_maker=self.decision_maker,
            satellite_strategy=self.satellite,
            total_capital=total_capital,
            satellite_ratio=satellite_capital / total_capital,
        )

        # 위성 포지션 추적: symbol → {side, entry_price, sl, tp, qty, risk_amount}
        self.satellite_positions = {}

        # ── 대시보드용 상태 저장 ──
        self.status = {
            'trade_log': [],        # 최근 거래 이력
            'started_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        # 개별 코인용 상태
        self.symbol_status = {
            sym: {
                'scan_count': 0,
                'last_scan': None,
                'last_signal': None,
                'price': 0.0,
                'prev_price': 0.0
            } for sym in self.symbols
        }

        # 트레이딩뷰 웹후크 브릿지 초기화 (보조 트리거)
        self.bridge = TVBridge(self)
        
        mode = "TESTNET" if self.use_testnet else "MAINNET"
        print(f"\n{'='*50}")
        print(f"아이린(Irene): v4.2 바벨 전략 ICT + AI 트레이딩 에이전트 가동")
        print(f"모드: {mode} | 대상: {', '.join(self.symbols)} | 리스크: {os.getenv('RISK_PER_TRADE')}")
        print(f"🔵 코어  컨플루언스: {self.decision_maker.min_confluence}/{self.decision_maker.max_score} (LTF스캘프 활성)")
        print(f"🔴 위성  자본: {satellite_capital:.0f}U | 레버리지 최대 {int(os.getenv('SATELLITE_MAX_LEV', 20))}배 | RR 3:1+")
        print(f"신급 모듈: 🧠군중심리 | 💎스마트머니 | 🐙세력감지 | 📰매크로뉴스")
        print(f"{'='*50}\n")

    def check_open_position(self, symbol):
        """특정 종목에 현재 열린 포지션이 있는지 확인합니다."""
        try:
            positions = self.executor.get_position_status(symbol)
            if positions:
                for pos in positions:
                    size = float(pos.get('contracts', 0) or 0)
                    if size > 0:
                        side = pos.get('side', 'unknown')
                        entry = pos.get('entryPrice', 'N/A')
                        pnl = pos.get('unrealizedPnl', 0)
                        print(f"아이린: {symbol} 현재 {side} 포지션 보유 중 (진입가: {entry}, 미실현PnL: {pnl})")
                        return True
            return False
        except Exception as e:
            print(f"아이린: 포지션 확인 오류 ({symbol}): {e}")
            return False  # 확인 불가 시 안전하게 진입 안 함

    def execute_autonomous_trade(self, signal, df_entry, symbol):
        """
        자율 분석 결과에 따라 실제 주문을 실행합니다.
        """
        side = signal['action']

        print(f"\n{'─'*40}")
        print(f"🎯 아이린: {symbol} {side.upper()} 진입 신호 발동!")
        for reason in signal['reasons']:
            print(f"   → {reason}")
        print(f"{'─'*40}")

        try:
            # 1. SL/TP 자동 계산 (ICT 구조 기반)
            sl, tp = self.ict_engine.calculate_sl_tp(df_entry, side)
            if not sl or not tp:
                print(f"아이린: {symbol} SL/TP를 계산할 수 없어 진입을 포기합니다.")
                return

            current_price = df_entry.iloc[-1]['close']

            # 2. 손익비(R:R) 검증
            risk = abs(current_price - sl)
            reward = abs(tp - current_price)
            if risk == 0:
                print(f"아이린: {symbol} 리스크가 0이므로 진입을 취소합니다.")
                return

            rr_ratio = reward / risk
            is_valid, rr_msg = self.risk_manager.validate_setup(rr_ratio, min_rr=1.5)
            print(rr_msg)

            if not is_valid:
                print(f"아이린: {symbol} 손익비가 최소 기준(1.5) 미달 → 진입 취소")
                return

            # SL 거리 범위 검증 (0.5%~2.0%)
            sl_dist_pct = risk / current_price
            if sl_dist_pct < 0.005:
                print(f"아이린: {symbol} SL이 너무 타이트({sl_dist_pct*100:.2f}%) → 진입 취소 (최소 0.5%)")
                return
            if sl_dist_pct > 0.020:
                print(f"아이린: {symbol} SL이 너무 넓음({sl_dist_pct*100:.2f}%) → 진입 취소 (최대 2.0%)")
                return

            # 3. 잔고 조회 및 포지션 크기 계산
            balance = self.fetcher.fetch_balance('USDT')
            if balance is None or balance <= 0:
                print(f"아이린: 잔고 확인 불가 → 진입 중단")
                return

            risk_report = self.risk_manager.calculate_position_size(balance, current_price, sl)
            qty = risk_report['position_qty']
            lev = max(1, min(int(risk_report['required_leverage']), 20))  # 레버리지 1~20배 제한

            print(f"아이린: {symbol} 잔고={balance:.2f} USDT | 수량={qty:.6f} | 레버리지={lev}배")
            print(f"아이린: SL={sl} | TP={tp} | R:R={rr_ratio:.2f}")

            # 4. 주문 실행!
            order = self.executor.place_order(symbol, side, qty, lev, stop_loss=sl, take_profit=tp)

            if order:
                self.decision_maker.record_trade()
                self.status['trade_log'].append({
                    'time': time.strftime('%m/%d %H:%M'),
                    'symbol': symbol,
                    'side': side.upper(),
                    'qty': f'{qty:.6f}',
                    'sl': sl,
                    'tp': tp
                })
                print(f"🎉 아이린: {symbol} {side.upper()} 진입 성공! 쿨다운 {self.decision_maker.cooldown_minutes}분 시작")
            
        except Exception as e:
            print(f"아이린: {symbol} 자율 매매 실행 중 오류: {e}")

    def execute_satellite_trade(self, signal: dict, df_entry, symbol: str):
        """
        위성(공격) 전략 주문 실행.
        - 포지션 사이즈: satellite.risk_amount / SL 거리 (복리 배율 적용)
        - 레버리지: signal['leverage'] (역산값, 최대 20배)
        """
        side        = signal['action']
        risk_amount = signal['risk_amount']
        leverage    = signal['leverage']

        print(f"\n{'─'*40}")
        print(f"🚀 아이린 [위성] {symbol} {side.upper()} 진입 신호!")
        for r in signal['reasons']:
            print(f"   → {r}")
        print(f"{'─'*40}")

        try:
            sl, tp = self.ict_engine.calculate_sl_tp(df_entry, side)
            if not sl or not tp:
                print(f"[위성] {symbol} SL/TP 계산 실패 → 진입 취소")
                return

            current_price = df_entry.iloc[-1]['close']
            sl_dist = abs(current_price - sl)
            if sl_dist == 0:
                return

            # 손익비 재확인 (최소 3:1)
            tp_dist = abs(tp - current_price)
            rr = tp_dist / sl_dist
            if rr < self.satellite.min_rr:
                print(f"[위성] RR {rr:.1f} 미달 → 진입 취소")
                return

            qty = risk_amount / sl_dist
            lev = max(5, min(leverage, self.satellite.max_leverage))

            print(f"[위성] 잔고기준 리스크={risk_amount:.2f}U | 수량={qty:.6f} | 레버리지={lev}배")
            print(f"[위성] SL={sl:.0f} | TP={tp:.0f} | R:R={rr:.2f}")

            order = self.satellite_executor.place_order(symbol, side, qty, lev, stop_loss=sl, take_profit=tp)
            if order:
                self.satellite.last_trade_time = time.time()
                self.satellite_positions[symbol] = {
                    'side': side,
                    'entry_price': current_price,
                    'sl': sl, 'tp': tp, 'qty': qty,
                    'risk_amount': risk_amount,
                    'compound_factor': signal['compound_factor'],
                    'pyramid_done': False,  # 피라미딩 완료 여부
                }
                print(f"🎉 [위성] {symbol} {side.upper()} 진입 성공! 복리배율={signal['compound_factor']:.2f}x")

        except Exception as e:
            print(f"[위성] {symbol} 실행 오류: {e}")

    def _check_satellite_pyramid(self, symbol: str):
        """
        피라미딩 모니터: TP 50% 도달 시 추가 진입 + SL → BE 이동.
        """
        pos = self.satellite_positions.get(symbol)
        if not pos or pos.get('pyramid_done'):
            return

        try:
            df = self.satellite_fetcher.fetch_ohlcv(symbol, '1m', limit=2)
            if df is None or df.empty:
                return
            current_price = float(df.iloc[-1]['close'])
        except Exception:
            return

        entry = pos['entry_price']
        tp    = pos['tp']
        side  = pos['side']
        half_tp = (entry + tp) / 2

        triggered = (side == 'buy'  and current_price >= half_tp) or \
                    (side == 'sell' and current_price <= half_tp)

        if not triggered:
            return

        print(f"\n🔺 [위성 피라미딩] {symbol} TP 50% 도달 @ {current_price:.2f}")
        print(f"   half_tp={half_tp:.2f} | entry={entry:.2f} → SL을 BE로 이동")

        # 1. 추가 진입 (원래 수량과 동일, SL/TP 없이 시장가)
        try:
            lev = max(5, min(20, self.satellite.max_leverage))
            self.satellite_executor.place_order(symbol, side, pos['qty'], lev)
            print(f"🔺 [피라미딩] 추가 진입 성공 qty={pos['qty']:.6f}")
        except Exception as e:
            print(f"[피라미딩] 추가 진입 실패: {e}")
            return

        # 2. SL → entry price (원래 진입가 = BE)
        self.satellite_executor.set_trading_stop(symbol, stop_loss=round(entry, 2))

        # 3. 상태 업데이트
        pos['qty']         *= 2
        pos['sl']           = entry
        pos['pyramid_done'] = True
        print(f"🔺 [피라미딩] SL → {entry:.2f} (BE) | 총 qty={pos['qty']:.6f}")

    def _check_satellite_position_result(self, symbol: str):
        """
        위성 포지션 종료 여부 감지 → 복리 배율 자동 업데이트.
        포지션이 사라진 시점에 거래소 최근 PnL을 조회해 win/loss 판정.
        """
        if symbol not in self.satellite_positions:
            return

        if self._check_satellite_open(symbol):
            return  # 아직 열려 있음

        pos = self.satellite_positions.pop(symbol)
        try:
            # 위성 서브계정에서 최근 종료 손익 조회
            pnl = self._fetch_closed_pnl(symbol)
            if pnl is None:
                # 조회 실패 시 현재가 vs 진입가로 추정
                try:
                    df = self.fetcher.fetch_ohlcv(symbol, '1m', limit=2)
                    last_price = df.iloc[-1]['close'] if df is not None else pos['entry_price']
                except Exception:
                    last_price = pos['entry_price']
                price_diff = last_price - pos['entry_price']
                pnl = price_diff * pos['qty'] if pos['side'] == 'buy' else -price_diff * pos['qty']

            is_win = pnl > 0
            self.barbell.record_satellite_result(pnl, is_win)

        except Exception as e:
            print(f"[위성] {symbol} 결과 집계 오류: {e}")

    def _check_satellite_open(self, symbol: str) -> bool:
        """위성 서브계정 기준으로 포지션 보유 여부 확인."""
        try:
            positions = self.satellite_executor.get_position_status(symbol)
            if positions:
                for pos in positions:
                    if float(pos.get('contracts', 0) or 0) > 0:
                        return True
        except Exception:
            pass
        return False

    def _fetch_closed_pnl(self, symbol: str):
        """위성 서브계정에서 최근 종료 포지션 PnL 조회."""
        try:
            contract_symbol = symbol.replace('/', '')
            result = self.satellite_fetcher.exchange.fetch_closed_orders(
                contract_symbol, limit=1
            )
            if result:
                return float(result[-1].get('info', {}).get('cumRealisedPnl', 0) or 0)
        except Exception:
            pass
        return None

    def run_analysis_loop(self):
        """
        자율 ICT 분석 루프: 
        각 종목을 순회하며 멀티 타임프레임을 스캔하고, 
        컨플루언스 조건 충족 시 자동으로 진입합니다.
        """
        while True:
            for symbol in self.symbols:
                try:
                    print(f"\n[{time.strftime('%H:%M:%S')}] 아이린: {symbol} 멀티 타임프레임 스캔 중...")

                    # ── 위성 포지션 결과 감지 (먼저 체크) ──
                    self._check_satellite_position_result(symbol)

                    # ── 위성 피라미딩 체크 (포지션 보유 중이면 항상 확인) ──
                    if symbol in self.satellite_positions:
                        self._check_satellite_pyramid(symbol)

                    # 1. 멀티 타임프레임 데이터 수집
                    data = self.fetcher.fetch_top_down_data(symbol)
                    if not data:
                        print(f"아이린: {symbol} 데이터 수집 실패 → 다음 종목으로 스킵")
                        time.sleep(2)
                        continue

                    # 가격 데이터 캐싱 (대시보드 API 최적화)
                    df_5m = data.get('5m')
                    if df_5m is not None and len(df_5m) >= 2:
                        self.symbol_status[symbol]['price'] = float(df_5m.iloc[-1]['close'])
                        self.symbol_status[symbol]['prev_price'] = float(df_5m.iloc[-2]['close'])

                    # ── 2. 바벨 매니저로 코어 + 위성 동시 분석 ──
                    signals = self.barbell.analyze(data, symbol=symbol)
                    core_signal      = signals['core']
                    satellite_signal = signals['satellite']

                    # 대시보드용 상태 저장
                    self.symbol_status[symbol]['last_scan'] = time.strftime('%Y-%m-%d %H:%M:%S')
                    self.symbol_status[symbol]['last_signal'] = core_signal
                    self.symbol_status[symbol]['scan_count'] += 1

                    # 코어 분석 결과 출력
                    print(f"🔵 [코어] {symbol} 컨플루언스 = {core_signal['confluence']:.1f}/10.0")
                    for reason in core_signal['reasons']:
                        print(f"   → {reason}")

                    # 위성 신호 출력 (진입 아닌 경우 마지막 사유만)
                    if satellite_signal['action'] in ('buy', 'sell'):
                        print(f"🔴 [위성] {symbol} 신호 발생!")
                        for reason in satellite_signal['reasons']:
                            print(f"   → {reason}")
                    elif satellite_signal['reasons']:
                        print(f"🔴 [위성] {satellite_signal['reasons'][-1]}")

                    df_entry = data.get('5m')
                    if df_entry is None or df_entry.empty:
                        df_entry = data.get('15m')

                    # ── 3. 현재 포지션 확인 ──
                    has_core_position = self.check_open_position(symbol)

                    # ── 4. 코어 진입 ──
                    if not has_core_position and core_signal['action'] in ('buy', 'sell'):
                        if self.trading_paused:
                            print(f"⛔ [{symbol}] TRADING_PAUSED → 코어 신호 차단")
                        elif df_entry is not None:
                            self.execute_autonomous_trade(core_signal, df_entry, symbol)

                    elif has_core_position:
                        print(f"아이린: {symbol} 코어 포지션 보유 중 → 신규 진입 보류")

                    # ── 5. 위성 진입 (코어와 독립 — 별도 자본) ──
                    if (symbol not in self.satellite_positions
                            and satellite_signal['action'] in ('buy', 'sell')):
                        if self.trading_paused:
                            print(f"⛔ [{symbol}] TRADING_PAUSED → 위성 신호 차단")
                        elif df_entry is not None:
                            self.execute_satellite_trade(satellite_signal, df_entry, symbol)

                except Exception as e:
                    print(f"아이린: {symbol} 분석 루프 오류: {e}")

                # API 레이트 리밋 보호
                time.sleep(5)

            # 전체 종목 1사이클 후 대기
            time.sleep(40)

    def start(self):
        """
        웹후크 서버와 자율 분석 루프를 동시에 시작합니다.
        """
        # 1. 트레이딩뷰 웹후크 서버를 별도 스레드에서 시작 (보조 트리거)
        bridge_thread = threading.Thread(target=self.bridge.run, kwargs={'host': '0.0.0.0', 'port': 9090})
        bridge_thread.daemon = True
        bridge_thread.start()
        
        # 2. 자율 ICT 분석 루프 시작 (메인)
        self.run_analysis_loop()

if __name__ == "__main__":
    agent = IreneAgent()
    # 자율 매매 시스템 풀가동 (ICT 분석 루프 + 웹훅 보조)
    agent.start()

