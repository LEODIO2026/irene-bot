from flask import Flask, request, jsonify, render_template
import os
import threading
import time
import json
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class TVBridge:
    def __init__(self, agent_instance):
        self.app = Flask(__name__)
        self.agent = agent_instance
        self.passphrase = os.getenv('WEBHOOK_PASSPHRASE', 'irene_secret')
        self.backtest_status = "idle"  # idle, running, completed, error
        self.setup_routes()

    def setup_routes(self):
        @self.app.route('/health', methods=['GET'])
        def health():
            """Docker 헬스체크 전용 엔드포인트"""
            return jsonify({"status": "ok", "agent": "irene"}), 200

        @self.app.route('/api/status', methods=['GET'])
        def api_status():
            """실시간 상태 데이터 JSON API"""
            import time as _time
            status = self.agent.status if hasattr(self.agent, 'status') else {}
            
            # 잔고 조회
            try:
                balance = self.agent.fetcher.fetch_balance('USDT') or 0
            except:
                balance = 0

            # 가동 시간 계산
            started = status.get('started_at', '')
            try:
                start_dt = datetime.strptime(started, '%Y-%m-%d %H:%M:%S')
                uptime_sec = int((_time.time() - start_dt.timestamp()))
                h, r = divmod(uptime_sec, 3600)
                m, s = divmod(r, 60)
                uptime_str = f"{h}시간 {m}분"
            except:
                uptime_str = '-'

            # 포지션 조회
            try:
                open_positions = self.agent.fetcher.fetch_positions(symbols=self.agent.symbols)
            except:
                open_positions = {}

            symbols_data = []
            for sym in self.agent.symbols:
                sym_status = self.agent.symbol_status.get(sym, {})
                signal = sym_status.get('last_signal') or {}
                price = sym_status.get('price', 0)
                prev_price = sym_status.get('prev_price', 0)
                pos = open_positions.get(sym, None)

                symbols_data.append({
                    'symbol': sym,
                    'price': price,
                    'change_pct': round((price - prev_price) / prev_price * 100, 3) if prev_price else 0,
                    'confluence': signal.get('confluence', 0),
                    'action': signal.get('action', 'hold'),
                    'side': signal.get('side'),
                    'reasons': signal.get('reasons', []),
                    'scores': signal.get('scores', {}),
                    'god_tier': signal.get('god_tier', {}),     # ✨ OI/LS 실시간 데이터
                    'fear_greed': signal.get('god_tier', {}).get('crowd', {}).get('details', {}).get('fear_greed'),
                    'scan_count': sym_status.get('scan_count', 0),
                    'last_scan': sym_status.get('last_scan', '-'),
                    'position': pos,
                })

            return jsonify({
                'symbols': symbols_data,
                'balance': round(balance, 2),
                'trade_log': status.get('trade_log', [])[-10:],
                'uptime': uptime_str,
                'started_at': started,
                'mode': 'MAINNET' if not self.agent.use_testnet else 'TESTNET',
                'risk_pct': int(self.agent.risk_manager.risk_per_trade * 100),
                'min_confluence': self.agent.decision_maker.min_confluence,
                'max_score': self.agent.decision_maker.max_score,
                'server_time': _time.strftime('%Y-%m-%d %H:%M:%S'),
                'backtest_status': self.backtest_status
            })

        @self.app.route('/dashboard', methods=['GET'])
        def dashboard():
            """프리미엄 실시간 모니터링 대시보드"""
            return render_template('dashboard.html')

        # ── 백테스트 API ───────────────────────────
        
        @self.app.route('/api/backtest/run', methods=['POST'])
        def run_backtest():
            """비동기로 백테스트 실행"""
            if self.backtest_status == "running":
                return jsonify({"status": "error", "message": "백테스트가 이미 진행 중입니다."}), 400
            
            data = request.json or {}
            symbol = data.get('symbol', 'BTC/USDT')
            limit = data.get('limit', 2000)

            def backtest_task():
                try:
                    self.backtest_status = "running"
                    from core.backtester import Backtester
                    print(f"아이린 대시보드: 비동기 백테스트 스레드 시작 ({symbol}, {limit}봉)")
                    tester = Backtester(symbol=symbol, initial_balance=1000)

                    # 타임아웃 처리: 5분(300초) 초과 시 자동 중단
                    done = threading.Event()
                    run_error = [None]

                    def _run():
                        try:
                            tester.run(limit=limit)
                        except Exception as e:
                            run_error[0] = e
                        finally:
                            done.set()

                    inner = threading.Thread(target=_run, daemon=True)
                    inner.start()
                    finished = done.wait(timeout=300)

                    if not finished:
                        self.backtest_status = "error"
                        print(f"❌ 아이린 대시보드: 백테스트 타임아웃 — 5분 초과 ({symbol})")
                    elif run_error[0]:
                        raise run_error[0]
                    else:
                        self.backtest_status = "completed"
                        print(f"아이린 대시보드: 백테스트 스레드 완료 ({symbol})")
                except Exception as e:
                    self.backtest_status = "error"
                    print(f"❌ 아이린 대시보드: 백테스트 스레드 오류 ({symbol}): {e}")
                    import traceback
                    traceback.print_exc()
                finally:
                    # 3초 후 자동으로 idle로 복구 (UI에서 완료 상태를 잠시 보여주기 위함)
                    time.sleep(3)
                    self.backtest_status = "idle"

            thread = threading.Thread(target=backtest_task)
            thread.daemon = True
            thread.start()
            
            return jsonify({"status": "success", "message": "백테스트가 시작되었습니다."}), 200

        @self.app.route('/api/backtest/results', methods=['GET'])
        def get_backtest_results():
            """저장된 최신 백테스트 결과 반환"""
            data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
            file_path = os.path.join(data_dir, 'backtest_latest.json')
            
            if not os.path.exists(file_path):
                return jsonify({"status": "no_results"}), 200
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                return jsonify(results), 200
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500

        @self.app.route('/webhook', methods=['POST'])
        def webhook():
            data = request.json
            if not data:
                return jsonify({"status": "error", "message": "No data received"}), 400

            if data.get('passphrase') != self.passphrase:
                return jsonify({"status": "unauthorized"}), 401

            side = data.get('side')
            symbol = data.get('symbol', self.agent.symbols[0])
            sl = data.get('sl')
            tp = data.get('tp')
            
            threading.Thread(target=self.execute_signal, args=(side, symbol, sl, tp)).start()
            return jsonify({"status": "success"}), 200

    def execute_signal(self, side, symbol, sl=None, tp=None):
        try:
            df = self.agent.fetcher.fetch_ohlcv(symbol, timeframe='1h', limit=100)
            if df is None or df.empty: return
            current_price = df.iloc[-1]['close']

            if sl is None or tp is None:
                auto_sl, auto_tp = self.agent.ict_engine.calculate_sl_tp(df, side)
                sl = sl or auto_sl
                tp = tp or auto_tp

            balance = self.agent.fetcher.fetch_balance('USDT')
            if not balance: return

            risk_report = self.agent.risk_manager.calculate_position_size(balance, current_price, sl)
            qty = risk_report['position_qty']
            lev = int(risk_report['required_leverage'])
            
            self.agent.executor.place_order(symbol, side, qty, lev, stop_loss=sl, take_profit=tp)
        except Exception as e:
            print(f"아이린: 웹후크 처리 오류: {e}")

    def run(self, host='0.0.0.0', port=5000):
        self.app.run(host=host, port=port)
