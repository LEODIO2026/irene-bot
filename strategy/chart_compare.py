"""
주거래 vs 위성 전략 자본 곡선 비교 차트
────────────────────────────────────────────────
- 동일 초기 자본 1000 USDT, 1년 데이터
- 주거래: core/backtester.py (ICT 컨플루언스, risk 2.5%)
- 위성:   simulate_satellite (1D+4H+킬존+스윕, risk 1%)
"""

import sys, os, io
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.font_manager as fm

# macOS 한글 폰트 설정
_KR_FONTS = ['AppleGothic', 'Apple SD Gothic Neo', 'NanumGothic', 'Malgun Gothic']
_available = {f.name for f in fm.fontManager.ttflist}
for _f in _KR_FONTS:
    if _f in _available:
        plt.rcParams['font.family'] = _f
        break
plt.rcParams['axes.unicode_minus'] = False
from matplotlib.gridspec import GridSpec
from collections import defaultdict
from contextlib import redirect_stdout

from core.ict_engine import ICTEngine
from core.data_fetcher import DataFetcher
from strategy.sweep_reversal_backtester import calc_equity, is_kill_zone, find_sweep_reversal_setups
from strategy.compare_strategies import simulate_satellite, INITIAL_CAPITAL, RISK_PCT, RR


SYMBOL     = 'BTC/USDT'
LIMIT_15M  = 17520   # 1년
CORE_RISK  = 0.025   # 주거래 리스크 2.5%


# ── 주거래 equity curve 추출 ────────────────────────────────

def run_core_strategy(df_15m, df_4h, df_1d, limit=LIMIT_15M):
    """Backtester를 출력 억제 모드로 실행. 이미 수집된 데이터를 주입."""
    from core.backtester import Backtester
    from core.decision_maker import DecisionMaker
    from execution.risk_manager import RiskManager
    from datetime import timedelta

    bt = Backtester(symbol=SYMBOL, initial_balance=INITIAL_CAPITAL,
                    risk_per_trade=CORE_RISK)

    # 내부 run() 대신 데이터 주입 방식으로 실행
    _df15 = df_15m.copy()
    _df15['swing_high']  = _df15['high'].rolling(5, center=True).max()
    _df15['swing_low']   = _df15['low'].rolling(5, center=True).min()
    _df15['body_size']   = abs(_df15['close'] - _df15['open'])
    _df15['avg_body']    = _df15['body_size'].rolling(10).mean()
    _df15['roll_max_20'] = _df15['high'].shift(1).rolling(20).max()
    _df15['roll_min_20'] = _df15['low'].shift(1).rolling(20).min()

    _df4h = df_4h.copy()
    _df4h['ema50'] = _df4h['close'].ewm(span=50, adjust=False).mean()
    _df1d = df_1d.copy()
    _df1d['ema50'] = _df1d['close'].ewm(span=50, adjust=False).mean()

    h4_idx = d1_idx = 0
    current_trade = None

    with redirect_stdout(io.StringIO()):
        for i in range(100, len(_df15)):
            row = _df15.iloc[i]
            current_time = row['timestamp']

            while h4_idx + 1 < len(_df4h) and _df4h.iloc[h4_idx+1]['timestamp'] <= current_time:
                h4_idx += 1
            while d1_idx + 1 < len(_df1d) and _df1d.iloc[d1_idx+1]['timestamp'] <= current_time:
                d1_idx += 1

            if current_trade is not None:
                side = current_trade['side']
                sl, tp = current_trade['sl'], current_trade['tp']
                ep = current_trade['entry_price']
                exit_price, exit_type = None, None
                if side == 'buy':
                    if row['low'] <= sl:    exit_price, exit_type = sl, 'loss'
                    elif row['high'] >= tp: exit_price, exit_type = tp, 'profit'
                else:
                    if row['high'] >= sl:   exit_price, exit_type = sl, 'loss'
                    elif row['low'] <= tp:  exit_price, exit_type = tp, 'profit'
                if exit_price is None:
                    if (current_time - current_trade['entry_time']).total_seconds() / 3600 >= 48:
                        exit_price, exit_type = row['close'], 'time_stop'
                if exit_price:
                    qty = current_trade['qty']
                    pnl = ((exit_price - ep) * qty if side == 'buy' else (ep - exit_price) * qty)
                    net = pnl - (ep + exit_price) * qty * 0.0006
                    bt.balance += net
                    bt.equity_curve.append(round(bt.balance, 2))
                    current_trade.update({'exit_price': exit_price, 'exit_time': current_time,
                                          'pnl': round(net,2), 'result': exit_type, 'status': 'closed'})
                    current_trade = None
                continue

            if bt.loss_cooldown_until and current_time < bt.loss_cooldown_until:
                continue

            snap15 = _df15.iloc[i-100:i+1]
            snap4h = _df4h.iloc[max(0, h4_idx-99):h4_idx+1]
            snap1d = _df1d.iloc[max(0, d1_idx-59):d1_idx+1]
            htf_bias = 'bullish' if (not snap4h.empty and
                                     snap4h.iloc[-1]['close'] >= snap4h.iloc[-1]['ema50']) else 'bearish'
            mock_ext = bt.simulate_external_data(snap15, htf_bias)
            data_dict = {'15m': snap15, '4h': snap4h, '1d': snap1d, 'mock_external': mock_ext}
            analysis = bt.decision_maker.analyze_entry(data_dict, symbol=SYMBOL, current_time=current_time)

            if analysis['action'] in ('buy', 'sell'):
                h4_rsi = bt._calc_rsi(snap4h['close'], 14) if len(snap4h) >= 15 else 50.0
                if analysis['action'] == 'sell' and h4_rsi < 35: continue
                if analysis['action'] == 'buy'  and h4_rsi > 75: continue
                if not bt.ict_engine.is_kill_zone(current_time=current_time)['in_kill_zone'] \
                   and analysis['confluence'] < 5.0: continue
                if len(snap4h) >= 20 and not bt._check_4h_momentum(snap4h, analysis['action']): continue
                t = bt.open_trade(analysis['action'], row['close'], snap15, current_time, analysis)
                if t:
                    current_trade = t
                    if analysis['action'] == 'buy':
                        bt.consecutive_losses = 0
                    else:
                        pass

    trades = [t for t in bt.trades if t.get('status') == 'closed']
    return trades, bt.equity_curve


# ── equity curve → 날짜 기반 시리즈 ────────────────────────

def trades_to_equity_series(trades, equity_curve, initial=INITIAL_CAPITAL):
    """
    거래 목록과 equity_curve로 (날짜, 자본) 시리즈를 만든다.
    equity_curve[0] = initial, equity_curve[i] = i번째 거래 후 자본.
    """
    dates    = [None]   # 초기
    capitals = [initial]

    for i, t in enumerate(trades, start=1):
        date = t.get('exit_time') or t.get('entry_time')
        if hasattr(date, 'to_pydatetime'):
            date = date.to_pydatetime()
        dates.append(date)
        capital = equity_curve[i] if i < len(equity_curve) else capitals[-1]
        capitals.append(capital)

    # 첫 날짜: 첫 거래 날짜로 대체
    if len(dates) > 1 and dates[1]:
        dates[0] = dates[1]

    return dates, capitals


def sat_trades_to_equity_series(trades, initial=INITIAL_CAPITAL, risk_pct=RISK_PCT, rr=RR):
    """위성 전략 거래 목록으로 equity series 생성."""
    dates    = []
    capitals = [initial]
    capital  = initial

    for t in trades:
        date = t.get('entry_time')
        if hasattr(date, 'to_pydatetime'):
            date = date.to_pydatetime()
        dates.append(date)
        risk_amt = capital * risk_pct
        if t['result'] == 'win':
            capital += risk_amt * rr
        else:
            capital -= risk_amt
        capital = max(capital, 0)
        capitals.append(capital)

    # 첫 날짜 처리
    all_dates = [dates[0] if dates else None] + dates
    return all_dates, capitals


# ── 월별 ROI 집계 ────────────────────────────────────────────

def monthly_roi(trades, rr, initial=INITIAL_CAPITAL, risk_pct=RISK_PCT, is_core=False):
    """전략별 월별 ROI % 딕셔너리 반환."""
    monthly = defaultdict(list)
    for t in trades:
        date = t.get('exit_time') or t.get('entry_time')
        if date is None:
            continue
        m = date.strftime('%Y-%m')
        monthly[m].append(t)

    result = {}
    for m, mt in sorted(monthly.items()):
        if is_core:
            cap = initial
            for t in mt:
                risk_amt = cap * risk_pct
                if t.get('result') == 'profit':
                    cap += risk_amt * rr
                else:
                    cap -= risk_amt
                cap = max(cap, 0)
            result[m] = (cap - initial) / initial * 100
        else:
            eq = calc_equity(mt, rr, initial, risk_pct)
            result[m] = eq['roi']
    return result


# ── 차트 그리기 ─────────────────────────────────────────────

def draw_chart(core_trades, core_equity,
               sat_trades, sat_equity_dates, sat_equity_caps,
               out_path='strategy/equity_chart.png'):

    # 주거래 equity series
    core_dates, core_caps = trades_to_equity_series(core_trades, core_equity)

    # 월별 ROI
    core_monthly = monthly_roi(core_trades, rr=2.0, is_core=True)  # 주거래 RR ~2
    sat_monthly  = monthly_roi(sat_trades,  rr=RR,  is_core=False)
    all_months   = sorted(set(list(core_monthly.keys()) + list(sat_monthly.keys())))

    # ── 색상 팔레트 ──
    C_CORE = '#4C9BE8'   # 파란색 — 주거래
    C_SAT  = '#F5A623'   # 주황색 — 위성
    C_BG   = '#0D1117'
    C_GRID = '#21262D'
    C_TEXT = '#E6EDF3'

    fig = plt.figure(figsize=(16, 10), facecolor=C_BG)
    fig.suptitle('아이린 전략 비교  |  BTC/USDT 1년  |  초기자본 1,000 USDT',
                 color=C_TEXT, fontsize=14, fontweight='bold', y=0.98)

    gs = GridSpec(3, 2, figure=fig,
                  hspace=0.45, wspace=0.35,
                  left=0.07, right=0.97, top=0.93, bottom=0.07)

    ax_eq   = fig.add_subplot(gs[0:2, :])   # 상단 전체: 자본 곡선
    ax_roi  = fig.add_subplot(gs[2, 0])     # 하단 좌: 월별 ROI
    ax_stat = fig.add_subplot(gs[2, 1])     # 하단 우: 통계 요약

    for ax in [ax_eq, ax_roi, ax_stat]:
        ax.set_facecolor(C_BG)
        ax.tick_params(colors=C_TEXT, labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(C_GRID)
        ax.yaxis.label.set_color(C_TEXT)
        ax.xaxis.label.set_color(C_TEXT)
        ax.title.set_color(C_TEXT)
        ax.grid(True, color=C_GRID, linewidth=0.5, alpha=0.7)

    # ── (1) 자본 곡선 ──────────────────────────────────────
    valid_core = [(d, c) for d, c in zip(core_dates, core_caps) if d is not None]
    valid_sat  = [(d, c) for d, c in zip(sat_equity_dates, sat_equity_caps) if d is not None]

    if valid_core:
        cd, cc = zip(*valid_core)
        ax_eq.plot(cd, cc, color=C_CORE, linewidth=1.8,
                   label=f'주거래  최종 {cc[-1]:,.0f}U  ROI {(cc[-1]-INITIAL_CAPITAL)/INITIAL_CAPITAL*100:+.1f}%')
        ax_eq.fill_between(cd, INITIAL_CAPITAL, cc, alpha=0.08, color=C_CORE)

    if valid_sat:
        sd, sc = zip(*valid_sat)
        ax_eq.plot(sd, sc, color=C_SAT, linewidth=1.8,
                   label=f'위성 v3  최종 {sc[-1]:,.0f}U  ROI {(sc[-1]-INITIAL_CAPITAL)/INITIAL_CAPITAL*100:+.1f}%')
        ax_eq.fill_between(sd, INITIAL_CAPITAL, sc, alpha=0.08, color=C_SAT)

    ax_eq.axhline(INITIAL_CAPITAL, color='#888', linewidth=0.8, linestyle='--', alpha=0.6)
    ax_eq.set_title('누적 자본 곡선', fontsize=11, fontweight='bold')
    ax_eq.set_ylabel('자본 (USDT)', fontsize=9)
    ax_eq.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))
    ax_eq.legend(loc='upper left', fontsize=9,
                 facecolor='#161B22', edgecolor=C_GRID, labelcolor=C_TEXT)

    # ── (2) 월별 ROI 바 차트 ──────────────────────────────
    x = np.arange(len(all_months))
    w = 0.38
    core_rois = [core_monthly.get(m, 0) for m in all_months]
    sat_rois  = [sat_monthly.get(m, 0)  for m in all_months]

    bars_c = ax_roi.bar(x - w/2, core_rois, w, label='주거래', color=C_CORE, alpha=0.85)
    bars_s = ax_roi.bar(x + w/2, sat_rois,  w, label='위성 v3', color=C_SAT,  alpha=0.85)

    # 음수 바 색상 강조
    for bar, val in zip(bars_c, core_rois):
        if val < 0: bar.set_color('#E05A5A')
    for bar, val in zip(bars_s, sat_rois):
        if val < 0: bar.set_color('#E05A5A')

    ax_roi.axhline(0, color='#888', linewidth=0.8)
    ax_roi.set_title('월별 ROI (%)', fontsize=10, fontweight='bold')
    ax_roi.set_xticks(x)
    ax_roi.set_xticklabels([m[5:] for m in all_months], rotation=45, fontsize=7)
    ax_roi.legend(fontsize=8, facecolor='#161B22', edgecolor=C_GRID, labelcolor=C_TEXT)
    ax_roi.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:+.0f}%'))

    # ── (3) 통계 요약 테이블 ──────────────────────────────
    ax_stat.axis('off')

    core_wins   = sum(1 for t in core_trades if t.get('result') == 'profit')
    core_total  = len(core_trades)
    core_wr     = core_wins / core_total * 100 if core_total else 0
    core_final  = core_equity[-1] if core_equity else INITIAL_CAPITAL
    core_roi    = (core_final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    core_mdd    = _calc_mdd(core_equity)

    sat_wins    = sum(1 for t in sat_trades if t['result'] == 'win')
    sat_total   = len(sat_trades)
    sat_wr      = sat_wins / sat_total * 100 if sat_total else 0
    sat_eq_obj  = calc_equity(sat_trades, RR, INITIAL_CAPITAL, RISK_PCT)
    sat_roi     = sat_eq_obj['roi']
    sat_mdd     = sat_eq_obj['mdd']
    sat_final   = sat_eq_obj['final_capital']

    rows = [
        ['항목',          '주거래',                    '위성 v3'],
        ['총 거래',       f'{core_total}회',           f'{sat_total}회'],
        ['승률',          f'{core_wr:.1f}%',           f'{sat_wr:.1f}%'],
        ['ROI',           f'{core_roi:+.1f}%',         f'{sat_roi:+.1f}%'],
        ['MDD',           f'{core_mdd:.1f}%',          f'{sat_mdd:.1f}%'],
        ['최종 자본',     f'{core_final:,.0f} U',      f'{sat_final:,.0f} U'],
        ['리스크/거래',   f'{CORE_RISK*100:.1f}%',     f'{RISK_PCT*100:.1f}%'],
    ]

    table = ax_stat.table(
        cellText=rows[1:],
        colLabels=rows[0],
        cellLoc='center', loc='center',
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.1, 1.6)

    # 헤더 색상
    for j in range(3):
        table[0, j].set_facecolor('#21262D')
        table[0, j].set_text_props(color=C_TEXT, fontweight='bold')

    # 데이터 셀
    for i in range(1, len(rows)):
        for j in range(3):
            table[i, j].set_facecolor('#0D1117' if i % 2 == 0 else '#161B22')
            table[i, j].set_text_props(color=C_TEXT)

    # ROI 행 강조
    for j, val in enumerate([core_roi, sat_roi], start=1):
        color = '#1A4A2E' if val >= 0 else '#4A1A1A'
        table[3, j].set_facecolor(color)

    ax_stat.set_title('전략 비교 요약', fontsize=10, fontweight='bold')

    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=C_BG)
    plt.close()
    print(f"  💾 차트 저장 완료: {out_path}")
    return out_path


def _calc_mdd(equity_curve):
    peak = equity_curve[0]
    mdd  = 0.0
    for v in equity_curve:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100
        if dd > mdd: mdd = dd
    return round(mdd, 1)


# ── 메인 ────────────────────────────────────────────────────

def fetch_public_ohlcv(symbol, timeframe, limit):
    """API 키 없이 퍼블릭 OHLCV 데이터 수집 (페이지네이션 지원)."""
    import ccxt, time as _time
    exchange  = ccxt.bybit({'enableRateLimit': True,
                            'options': {'defaultType': 'linear'}})
    contract  = symbol.replace('/', '')   # BTC/USDT → BTCUSDT
    tf_ms     = exchange.parse_timeframe(timeframe) * 1000
    now       = exchange.milliseconds()
    since     = now - limit * tf_ms
    all_ohlcv = []
    remaining = limit

    while remaining > 0:
        batch = exchange.fetch_ohlcv(contract, timeframe,
                                     since=since, limit=min(remaining, 1000))
        if not batch:
            break
        all_ohlcv.extend(batch)
        remaining -= len(batch)
        since      = batch[-1][0] + tf_ms
        if len(batch) < 1000:
            break
        _time.sleep(exchange.rateLimit / 1000)

    df = pd.DataFrame(all_ohlcv, columns=['ts','open','high','low','close','volume'])
    df = df.drop_duplicates(subset=['ts']).sort_values('ts')
    df['timestamp'] = pd.to_datetime(df['ts'], unit='ms')
    df = df[['timestamp','open','high','low','close','volume']].astype(
        {'open': float, 'high': float, 'low': float, 'close': float, 'volume': float}
    )
    return df.tail(limit).reset_index(drop=True)


if __name__ == '__main__':
    print('\n' + '='*60)
    print('  주거래 vs 위성 전략 차트 생성')
    print('='*60)

    ict = ICTEngine()

    # 공통 데이터 수집 (퍼블릭 API)
    print('\n📡 데이터 수집 중...')
    df_15m = fetch_public_ohlcv(SYMBOL, '15m', LIMIT_15M)
    df_4h  = fetch_public_ohlcv(SYMBOL, '4h',  LIMIT_15M//16+100)
    df_1d  = fetch_public_ohlcv(SYMBOL, '1d',  LIMIT_15M//96+50)

    df_15m = df_15m.copy()
    for col, func in [
        ('body_size',   lambda d: abs(d['close'] - d['open'])),
        ('avg_body',    lambda d: abs(d['close']-d['open']).rolling(10).mean()),
        ('swing_high',  lambda d: d['high'].rolling(5, center=True).max()),
        ('swing_low',   lambda d: d['low'].rolling(5, center=True).min()),
        ('roll_max_20', lambda d: d['high'].shift(1).rolling(20).max()),
        ('roll_min_20', lambda d: d['low'].shift(1).rolling(20).min()),
    ]:
        df_15m[col] = func(df_15m)
    print(f'  ✅ 15m({len(df_15m)})  4h({len(df_4h)})  1d({len(df_1d)})')

    # 위성 시뮬레이션
    print('\n  위성 전략 시뮬레이션 중...', end='', flush=True)
    sat_trades = simulate_satellite(df_15m, df_4h, df_1d, ict)
    sat_dates, sat_caps = sat_trades_to_equity_series(sat_trades)
    print(f' {len(sat_trades)}건 완료')

    # 주거래 시뮬레이션
    print('  주거래 전략 시뮬레이션 중...', end='', flush=True)
    core_trades, core_equity = run_core_strategy(df_15m, df_4h, df_1d)
    print(f' {len(core_trades)}건 완료')

    # 차트 생성
    print('\n  차트 생성 중...')
    out = draw_chart(core_trades, core_equity,
                     sat_trades, sat_dates, sat_caps)
    print('\n  ✅ 완료! 파일을 열어보세요:', out)
    print('='*60)
