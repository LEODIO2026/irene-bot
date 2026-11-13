import threading

from flask import Flask, jsonify, render_template, request


def create_app(engine):
    app = Flask(__name__)

    @app.route('/')
    def index():
        return render_template('terminal.html')

    @app.route('/health')
    def health():
        return jsonify(status='ok', mode='PAPER')

    @app.route('/api/state')
    def state():
        return jsonify(engine.state())

    @app.route('/api/pause', methods=['POST'])
    def pause():
        engine.paused = bool((request.get_json(silent=True) or {}).get('paused', not engine.paused))
        return jsonify(paused=engine.paused)

    @app.route('/api/reset', methods=['POST'])
    def reset():
        engine.reset()
        return jsonify(ok=True)

    return app


def serve(engine):
    threading.Thread(target=engine.run_forever, daemon=True).start()
    cfg = engine.cfg
    print(f'📄 모의거래 터미널: http://{cfg.host}:{cfg.port}  (데이터: {engine.source.name})')
    print('   실제 주문·지갑·API 키를 사용하지 않습니다. 가상 잔고로만 거래합니다.')
    create_app(engine).run(host=cfg.host, port=cfg.port, debug=False, use_reloader=False)
