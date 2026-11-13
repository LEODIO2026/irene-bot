"""실행:  python -m paper_terminal            (실시간 데이터)
        python -m paper_terminal --source sim   (가상 시장, 인터넷 불필요)
"""
import argparse

from .config import Config
from .engine import Engine
from .sources import SimClock
from .web import serve


def main():
    ap = argparse.ArgumentParser(description='아이린 모의거래 터미널 (실제 돈 사용 안 함)')
    ap.add_argument('--source', choices=['live', 'sim'])
    ap.add_argument('--balance', type=float, help='가상 시작 잔고(USD)')
    ap.add_argument('--port', type=int)
    ap.add_argument('--host')
    ap.add_argument('--poll', type=float, help='확인 주기(초)')
    ap.add_argument('--db', help='기록 파일 경로')
    a = ap.parse_args()

    cfg = Config()
    for attr, val in (('source', a.source), ('start_balance', a.balance), ('port', a.port),
                      ('host', a.host), ('poll_seconds', a.poll), ('db_path', a.db)):
        if val is not None:
            setattr(cfg, attr, val)
    if cfg.source == 'sim':
        if a.poll is None:
            cfg.poll_seconds = 1          # 가상 시장은 1초에 30초씩 빨리 감기
        if a.db is None:
            cfg.db_path = cfg.db_path.replace('.db', '_sim.db')   # 실시간 기록과 섞이지 않게
        serve(Engine(cfg, clock=SimClock()))
    else:
        serve(Engine(cfg))


if __name__ == '__main__':
    main()
