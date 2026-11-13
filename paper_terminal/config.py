import os
from dataclasses import dataclass, field


def _f(name, default):
    return float(os.getenv(name, default))


def _i(name, default):
    return int(os.getenv(name, default))


@dataclass
class Config:
    # ── 계좌 ──
    start_balance: float = field(default_factory=lambda: _f('PAPER_START_BALANCE', 44.82))

    # ── 데이터 ──
    source: str = field(default_factory=lambda: os.getenv('PAPER_SOURCE', 'live'))  # live | sim
    chain: str = field(default_factory=lambda: os.getenv('PAPER_CHAIN', 'solana'))
    poll_seconds: float = field(default_factory=lambda: _f('PAPER_POLL_SECONDS', 30))
    watch_hours: float = field(default_factory=lambda: _f('PAPER_WATCH_HOURS', 6))
    watch_max: int = field(default_factory=lambda: _i('PAPER_WATCH_MAX', 90))

    # ── 스캐너 (신규 페어 + 거래량 급증) ──
    max_pair_age_hours: float = field(default_factory=lambda: _f('PAPER_MAX_PAIR_AGE_HOURS', 48))
    min_vol_m5: float = field(default_factory=lambda: _f('PAPER_MIN_VOL_M5', 3000))
    vol_spike_mult: float = field(default_factory=lambda: _f('PAPER_VOL_SPIKE_MULT', 2.0))
    min_buy_sell_ratio: float = field(default_factory=lambda: _f('PAPER_MIN_BUY_SELL_RATIO', 1.2))
    min_chg_m5: float = field(default_factory=lambda: _f('PAPER_MIN_CHG_M5', 2.0))
    max_chg_m5: float = field(default_factory=lambda: _f('PAPER_MAX_CHG_M5', 40.0))
    cooldown_minutes: float = field(default_factory=lambda: _f('PAPER_COOLDOWN_MINUTES', 30))

    # ── 러그 체크 ──
    min_liquidity: float = field(default_factory=lambda: _f('PAPER_MIN_LIQUIDITY', 15000))
    min_pair_age_minutes: float = field(default_factory=lambda: _f('PAPER_MIN_PAIR_AGE_MINUTES', 10))
    max_fdv_liq_ratio: float = field(default_factory=lambda: _f('PAPER_MAX_FDV_LIQ_RATIO', 40))
    max_rug_score: float = field(default_factory=lambda: _f('PAPER_MAX_RUG_SCORE', 30))
    min_lp_locked_pct: float = field(default_factory=lambda: _f('PAPER_MIN_LP_LOCKED_PCT', 80))
    # RugCheck 응답을 못 받으면 진입하지 않는다 (모르면 안 산다)
    rug_fail_closed: bool = field(default_factory=lambda: os.getenv('PAPER_RUG_FAIL_CLOSED', 'True') == 'True')

    # ── 사이저 (잔고 비례 포지션) ──
    risk_per_trade: float = field(default_factory=lambda: _f('PAPER_RISK_PER_TRADE', 0.02))
    max_position_pct: float = field(default_factory=lambda: _f('PAPER_MAX_POSITION_PCT', 0.20))
    max_pool_pct: float = field(default_factory=lambda: _f('PAPER_MAX_POOL_PCT', 0.01))
    max_open_positions: int = field(default_factory=lambda: _i('PAPER_MAX_OPEN_POSITIONS', 4))
    min_ticket: float = field(default_factory=lambda: _f('PAPER_MIN_TICKET', 3.0))
    halt_drawdown: float = field(default_factory=lambda: _f('PAPER_HALT_DRAWDOWN', 0.40))

    # ── 실행기 (비용·청산 규칙) ──
    dex_fee: float = field(default_factory=lambda: _f('PAPER_DEX_FEE', 0.003))
    network_fee: float = field(default_factory=lambda: _f('PAPER_NETWORK_FEE', 0.02))
    stop_loss: float = field(default_factory=lambda: _f('PAPER_STOP_LOSS', 0.15))
    take_profit: float = field(default_factory=lambda: _f('PAPER_TAKE_PROFIT', 0.35))
    trail_arm: float = field(default_factory=lambda: _f('PAPER_TRAIL_ARM', 0.15))
    trail_gap: float = field(default_factory=lambda: _f('PAPER_TRAIL_GAP', 0.10))
    max_hold_minutes: float = field(default_factory=lambda: _f('PAPER_MAX_HOLD_MINUTES', 90))
    liq_drop_exit: float = field(default_factory=lambda: _f('PAPER_LIQ_DROP_EXIT', 0.5))
    missing_polls_exit: int = field(default_factory=lambda: _i('PAPER_MISSING_POLLS_EXIT', 5))

    # ── 웹 ──
    host: str = field(default_factory=lambda: os.getenv('PAPER_HOST', '127.0.0.1'))
    port: int = field(default_factory=lambda: _i('PAPER_PORT', 9191))
    db_path: str = field(default_factory=lambda: os.getenv(
        'PAPER_DB_PATH', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'paper_terminal.db')))
