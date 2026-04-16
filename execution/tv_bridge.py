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
        self._assistant = None  # lazy init (API key may not be set at startup)
        self.setup_routes()

    @property
    def assistant(self):
        if self._assistant is None:
            from execution.trade_assistant import TradeAssistant
            self._assistant = TradeAssistant(self.agent)
        return self._assistant

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
            
            # 잔고 조회 (코어 + 위성)
            try:
                balance = self.agent.fetcher.fetch_balance('USDT') or 0
            except:
                balance = 0

            try:
                satellite_balance = self.agent.satellite_fetcher.fetch_balance('USDT') or 0
            except:
                satellite_balance = 0

            try:
                satellite_compound = self.agent.satellite.compound_factor
            except:
                satellite_compound = 1.0

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

            # 포지션 조회 (코어 + 위성)
            try:
                open_positions = self.agent.fetcher.fetch_positions(symbols=self.agent.symbols)
            except:
                open_positions = {}

            try:
                satellite_positions = self.agent.satellite_fetcher.fetch_positions(symbols=self.agent.symbols)
            except:
                satellite_positions = {}

            symbols_data = []
            for sym in self.agent.symbols:
                sym_status = self.agent.symbol_status.get(sym, {})
                signal = sym_status.get('last_signal') or {}
                price = sym_status.get('price', 0)
                prev_price = sym_status.get('prev_price', 0)
                pos = open_positions.get(sym, None)

                sat_signal = sym_status.get('last_satellite_signal') or {}
                sat_pos = satellite_positions.get(sym, None)
                symbols_data.append({
                    'symbol': sym,
                    'price': price,
                    'change_pct': round((price - prev_price) / prev_price * 100, 3) if prev_price else 0,
                    'confluence': signal.get('confluence', 0),
                    'action': signal.get('action', 'hold'),
                    'side': signal.get('side'),
                    'reasons': signal.get('reasons', []),
                    'risk_pct': signal.get('risk_pct', 0.01),
                    'scores': signal.get('scores', {}),
                    'god_tier': signal.get('god_tier', {}),
                    'fear_greed': signal.get('god_tier', {}).get('crowd', {}).get('details', {}).get('fear_greed'),
                    'scan_count': sym_status.get('scan_count', 0),
                    'last_scan': sym_status.get('last_scan', '-'),
                    'position': pos,
                    'satellite_position': sat_pos,
                    'satellite_action': sat_signal.get('action', 'hold'),
                    'satellite_side': sat_signal.get('side'),
                    'satellite_reasons': sat_signal.get('reasons', []),
                    'satellite_confluence': sat_signal.get('confluence', 0),
                })

            return jsonify({
                'symbols': symbols_data,
                'balance': round(balance, 2),
                'satellite_balance': round(satellite_balance, 2),
                'satellite_compound': round(satellite_compound, 2),
                'trade_log': status.get('trade_log', [])[-10:],
                'uptime': uptime_str,
                'started_at': started,
                'mode': 'MAINNET' if not self.agent.use_testnet else 'TESTNET',
                'risk_pct': int(self.agent.risk_manager.risk_per_trade * 100),
                'min_confluence': self.agent.decision_maker.min_confluence,
                'max_score': self.agent.decision_maker.max_score,
                'server_time': (lambda kst: kst.strftime('%H:%M:%S'))(
                    __import__('datetime').datetime.utcnow() + __import__('datetime').timedelta(hours=9)
                ),
                'killzone': (lambda h: (
                    '🟢 런던' if 15 <= h < 17 else
                    '🟢 뉴욕' if h >= 22 or h < 1 else
                    '🟡 아시안' if 1 <= h < 4 else
                    '⚪ 대기'
                ))( (__import__('datetime').datetime.utcnow() + __import__('datetime').timedelta(hours=9)).hour ),
                'backtest_status': self.backtest_status,
                'pending_proposals': self.agent.status.get('pending_proposals', {})
            })

        @self.app.route('/dashboard', methods=['GET'])
        def dashboard():
            """프리미엄 실시간 모니터링 대시보드"""
            return render_template('dashboard.html')

        @self.app.route('/trade-assistant', methods=['GET'])
        def trade_assistant_page():
            """반자동 대화형 트레이딩 어시스턴트 페이지"""
            return render_template('trade_assistant.html')

        @self.app.route('/api/trade-chat', methods=['POST'])
        def trade_chat():
            """Claude와 대화 — 텍스트 + 선택적 차트 이미지 (최대 5장)"""
            data = request.get_json(silent=True) or {}
            session_id = data.get('session_id', 'default')
            user_text  = data.get('message', '').strip()
            symbol     = data.get('symbol', 'BTC/USDT')
            model      = data.get('model', 'claude-3-5-sonnet-20241022')

            # 멀티 이미지: images=[{b64,mime},...] 또는 하위호환 단일 image_b64
            images = data.get('images') or []
            if not images and data.get('image_b64'):
                images = [{'b64': data['image_b64'],
                           'mime': data.get('image_mime', 'image/png')}]
            images = images[:5]  # 최대 5장 강제

            if not user_text and not images:
                return jsonify({'error': '메시지 또는 이미지가 필요합니다.'}), 400

            try:
                result = self.assistant.chat(
                    session_id=session_id,
                    user_text=user_text,
                    images=images,
                    symbol=symbol,
                    model=model,
                )
                return jsonify(result), 200
            except ValueError as e:
                return jsonify({'error': str(e), 'need_api_key': True}), 503
            except Exception as e:
                import traceback; traceback.print_exc()
                return jsonify({'error': str(e)}), 500

        @self.app.route('/api/trade-execute', methods=['POST'])
        def trade_execute():
            """확정된 거래 실행"""
            data = request.get_json(silent=True) or {}
            if data.get('passphrase') != self.passphrase:
                return jsonify({'error': 'unauthorized'}), 401

            symbol     = data.get('symbol', 'BTC/USDT')
            side       = data.get('side', '').lower()
            sl         = data.get('sl')
            tp         = data.get('tp')
            session_id = data.get('session_id', 'default')

            if side not in ('buy', 'sell'):
                return jsonify({'error': 'side는 buy 또는 sell이어야 합니다.'}), 400
            if sl is None or tp is None:
                return jsonify({'error': 'sl과 tp가 필요합니다.'}), 400

            try:
                result = self.assistant.execute_trade(
                    symbol=symbol, side=side,
                    sl=float(sl), tp=float(tp),
                    session_id=session_id,
                )
                return jsonify(result), 200 if result['success'] else 500
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)}), 500

        @self.app.route('/api/trade-close', methods=['POST'])
        def trade_close():
            """포지션 청산"""
            data = request.get_json(silent=True) or {}
            if data.get('passphrase') != self.passphrase:
                return jsonify({'error': 'unauthorized'}), 401

            symbol     = data.get('symbol', 'BTC/USDT')
            session_id = data.get('session_id', 'default')

            try:
                result = self.assistant.close_position(symbol=symbol, session_id=session_id)
                return jsonify(result), 200 if result['success'] else 500
            except Exception as e:
                return jsonify({'success': False, 'message': str(e)}), 500

        @self.app.route('/api/trade-reset', methods=['POST'])
        def trade_reset():
            """대화 세션 초기화"""
            data = request.get_json(silent=True) or {}
            session_id = data.get('session_id', 'default')
            if self._assistant:
                self._assistant.clear_session(session_id)
            return jsonify({'status': 'ok'}), 200

        @self.app.route('/api/chat-logs', methods=['GET'])
        def chat_logs_list():
            """저장된 채팅 로그 목록"""
            return jsonify(self.assistant.list_chat_logs()), 200

        @self.app.route('/api/chat-logs/<session_id>', methods=['GET'])
        def chat_log_detail(session_id):
            """특정 세션 채팅 로그 상세"""
            log = self.assistant.get_chat_log(session_id)
            if not log:
                return jsonify({'error': '로그 없음'}), 404
            return jsonify(log), 200

        @self.app.route('/chat-logs', methods=['GET'])
        def chat_logs_page():
            """채팅 로그 열람 페이지"""
            return render_template('chat_logs.html')

        @self.app.route('/api/trade-position', methods=['GET'])
        def trade_position():
            """코어 계정 현재 포지션 조회"""
            symbol = request.args.get('symbol', 'BTC/USDT')
            try:
                positions = self.agent.fetcher.fetch_positions(symbols=[symbol])
                pos = positions.get(symbol)
                snap = None
                if pos:
                    df = self.agent.fetcher.fetch_ohlcv(symbol, '1h', 2)
                    price = float(df.iloc[-1]['close']) if df is not None and not df.empty else 0
                    snap = {**pos, 'current_price': price}
                return jsonify({'position': snap}), 200
            except Exception as e:
                return jsonify({'error': str(e)}), 500

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
            
            account = data.get('account', 'core')  # 'core' | 'satellite'
            if account == 'satellite':
                threading.Thread(target=self.execute_satellite_signal, args=(side, symbol, sl, tp)).start()
            else:
                threading.Thread(target=self.execute_signal, args=(side, symbol, sl, tp)).start()
            return jsonify({"status": "success", "account": account}), 200

    def execute_signal(self, side, symbol, sl=None, tp=None):
        try:
            df = self.agent.fetcher.fetch_ohlcv(symbol, timeframe='1h', limit=100)
            if df is None or df.empty: return
            current_price = df.iloc[-1]['close']

            if sl is None:
                auto_sl, _ = self.agent.ict_engine.calculate_sl_tp(df, side)
                sl = auto_sl

            # TP는 항상 SL 기준 1:3 고정
            risk = abs(current_price - sl)
            tp = round(current_price + risk * 3, 4) if side == 'buy' else round(current_price - risk * 3, 4)

            balance = self.agent.fetcher.fetch_balance('USDT')
            if not balance: return

            risk_report = self.agent.risk_manager.calculate_position_size(balance, current_price, sl)
            qty = risk_report['position_qty']
            lev = max(2, int(risk_report['required_leverage']) + 1)

            order = self.agent.executor.place_order(symbol, side, qty, lev, stop_loss=sl, take_profit=tp)
            if order:
                import time as _t
                self.agent._append_trade_log({
                    'time':        _t.strftime('%m/%d %H:%M'),
                    'ts':          int(_t.time() * 1000),
                    'symbol':      symbol,
                    'side':        side.upper(),
                    'qty':         f'{qty:.6f}',
                    'entry_price': round(float(current_price), 4),
                    'sl':          sl,
                    'tp':          tp,
                    'account':     'core',
                    'pnl':         None,
                    'exit_price':  None,
                })
        except Exception as e:
            print(f"아이린: 웹후크 처리 오류: {e}")

    def execute_satellite_signal(self, side, symbol, sl=None, tp=None):
        try:
            df = self.agent.satellite_fetcher.fetch_ohlcv(symbol, timeframe='1h', limit=100)
            if df is None or df.empty: return
            current_price = df.iloc[-1]['close']

            if sl is None:
                auto_sl, _ = self.agent.ict_engine.calculate_sl_tp(df, side)
                sl = auto_sl

            # TP는 항상 SL 기준 1:3 고정
            risk = abs(current_price - sl)
            tp = round(current_price + risk * 3, 4) if side == 'buy' else round(current_price - risk * 3, 4)

            balance = self.agent.satellite_fetcher.fetch_balance('USDT')
            if not balance: return

            risk_report = self.agent.risk_manager.calculate_position_size(balance, current_price, sl)
            qty = risk_report['position_qty']
            lev = max(2, int(risk_report['required_leverage']) + 1)

            order = self.agent.satellite_executor.place_order(symbol, side, qty, lev, stop_loss=sl, take_profit=tp)
            if order:
                import time as _t
                self.agent._append_trade_log({
                    'time':        _t.strftime('%m/%d %H:%M'),
                    'ts':          int(_t.time() * 1000),
                    'symbol':      symbol,
                    'side':        side.upper(),
                    'qty':         f'{qty:.6f}',
                    'entry_price': round(float(current_price), 4),
                    'sl':          sl,
                    'tp':          tp,
                    'account':     'satellite',
                    'pnl':         None,
                    'exit_price':  None,
                })
                print(f"아이린[위성]: {symbol} {side.upper()} 웹훅 진입 성공.")
        except Exception as e:
            print(f"아이린[위성]: 웹훅 처리 오류: {e}")

    def run(self, host='0.0.0.0', port=5000):
        self.app.run(host=host, port=port)
