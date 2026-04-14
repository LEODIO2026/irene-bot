"""
아이린 백테스트 결과 시각화
"""
import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.gridspec as gridspec
from matplotlib import rcParams
import numpy as np
from datetime import datetime
import os

# 한글 폰트 설정
rcParams['font.family'] = ['AppleGothic', 'Malgun Gothic', 'NanumGothic', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False

def load_data():
    root = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(root, 'data', 'backtest_latest.json')
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def plot_backtest(data):
    summary  = data['summary']
    trades   = data['trades']
    equity   = data['equity_curve']
    symbol   = data.get('symbol', 'BTC/USDT')

    fig = plt.figure(figsize=(18, 12), facecolor='#0d1117')
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)

    txt_color   = '#e6edf3'
    green       = '#3fb950'
    red         = '#f85149'
    blue        = '#58a6ff'
    yellow      = '#d29922'
    purple      = '#bc8cff'
    bg_panel    = '#161b22'
    grid_color  = '#21262d'

    # ─────────────────────────────────────────────────────────────
    # 1. 자산 곡선 (상단 전체 폭)
    # ─────────────────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :])
    ax1.set_facecolor(bg_panel)

    eq  = np.array(equity)
    xs  = np.arange(len(eq))

    # 그라디언트 효과 (fill_between)
    final_val = eq[-1]
    init_val  = eq[0]
    color_line = green if final_val >= init_val else red
    ax1.plot(xs, eq, color=color_line, linewidth=1.8, zorder=3)
    ax1.fill_between(xs, eq, init_val, where=eq >= init_val,
                     alpha=0.18, color=green, zorder=2)
    ax1.fill_between(xs, eq, init_val, where=eq < init_val,
                     alpha=0.18, color=red, zorder=2)
    ax1.axhline(init_val, color=txt_color, linewidth=0.7, linestyle='--', alpha=0.4)

    # 거래 진입/청산 마커
    idx_offset = 0
    for t in trades:
        result = t.get('result', '')
        entry_eq_idx = t.get('entry_time', '')
        # equity curve 인덱스를 추정 (거래 순서 기반)
        c = green if result == 'profit' else red
        # 간단히: trades 순서대로 equity 인덱스 대응

    # MDD 영역 표시
    peak, mdd_start, mdd_end, cur_peak = init_val, 0, 0, 0
    for xi, e in enumerate(eq):
        if e > peak:
            peak = e
            cur_peak = xi
        dd = (peak - e) / peak * 100
        if dd == summary['max_drawdown']:
            mdd_end = xi
            mdd_start = cur_peak

    ax1.axvspan(mdd_start, mdd_end, alpha=0.12, color=red, label=f"최대 낙폭 구간")

    roi_str   = f"{summary['roi']:+.2f}%"
    roi_color = green if summary['roi'] >= 0 else red
    ax1.set_title(f"아이린(Irene) v3  |  {symbol}  |  수익률 {roi_str}",
                  color=txt_color, fontsize=14, fontweight='bold', pad=10)
    ax1.set_ylabel('잔고 (USDT)', color=txt_color, fontsize=10)
    ax1.tick_params(colors=txt_color, labelsize=9)
    ax1.spines[:].set_color(grid_color)
    ax1.grid(color=grid_color, linewidth=0.5)
    ax1.yaxis.label.set_color(txt_color)

    # 최종 잔고 annotation
    ax1.annotate(f"  {final_val:,.0f} USDT",
                 xy=(len(eq)-1, final_val),
                 color=color_line, fontsize=10, fontweight='bold', va='center')

    # ─────────────────────────────────────────────────────────────
    # 2. 거래별 PnL 바 차트 (중단 왼쪽)
    # ─────────────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1, :2])
    ax2.set_facecolor(bg_panel)

    pnls   = [t.get('pnl', 0) for t in trades]
    colors = [green if p >= 0 else red for p in pnls]
    bars   = ax2.bar(range(len(pnls)), pnls, color=colors, alpha=0.85, width=0.7)

    ax2.axhline(0, color=txt_color, linewidth=0.8, alpha=0.5)
    # 누적 PnL 라인
    cum_pnl = np.cumsum(pnls)
    ax2_twin = ax2.twinx()
    ax2_twin.plot(cum_pnl, color=blue, linewidth=1.5, linestyle='--', alpha=0.8, label='누적 PnL')
    ax2_twin.tick_params(colors=blue, labelsize=8)
    ax2_twin.spines[:].set_color(grid_color)
    ax2_twin.set_ylabel('누적 PnL (USDT)', color=blue, fontsize=9)

    ax2.set_title('거래별 손익 (PnL)', color=txt_color, fontsize=11, fontweight='bold')
    ax2.set_xlabel('거래 번호', color=txt_color, fontsize=9)
    ax2.set_ylabel('PnL (USDT)', color=txt_color, fontsize=9)
    ax2.tick_params(colors=txt_color, labelsize=8)
    ax2.spines[:].set_color(grid_color)
    ax2.grid(color=grid_color, linewidth=0.4, axis='y')

    # ─────────────────────────────────────────────────────────────
    # 3. 도넛 차트 (승/패 비율)
    # ─────────────────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 2])
    ax3.set_facecolor(bg_panel)

    wins   = summary['win_trades']
    losses = summary['loss_trades']
    forced = summary['total_trades'] - wins - losses

    sizes  = [wins, losses]
    labels = [f'익절  {wins}', f'손절  {losses}']
    clrs   = [green, red]
    if forced > 0:
        sizes.append(forced)
        labels.append(f'강제종료 {forced}')
        clrs.append(yellow)

    wedges, texts = ax3.pie(sizes, labels=None, colors=clrs,
                            startangle=90, wedgeprops={'width': 0.55, 'edgecolor': bg_panel, 'linewidth': 2})
    ax3.set_title('승/패 비율', color=txt_color, fontsize=11, fontweight='bold')
    legend_patches = [mpatches.Patch(color=c, label=l) for c, l in zip(clrs, labels)]
    ax3.legend(handles=legend_patches, loc='lower center', fontsize=9,
               framealpha=0, labelcolor=txt_color, ncol=1)
    ax3.text(0, 0, f"{summary['win_rate']:.1f}%\n승률", ha='center', va='center',
             color=txt_color, fontsize=12, fontweight='bold')

    # ─────────────────────────────────────────────────────────────
    # 4. 핵심 지표 패널 (하단 왼쪽)
    # ─────────────────────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[2, 0])
    ax4.set_facecolor(bg_panel)
    ax4.axis('off')

    metrics = [
        ("총 수익률",  f"{summary['roi']:+.2f}%",        green if summary['roi'] >= 0 else red),
        ("최종 잔고",  f"{summary['final_balance']:,.0f} USDT", txt_color),
        ("순 이익",    f"{summary['net_profit']:+.2f} USDT",   green if summary['net_profit'] >= 0 else red),
        ("총 거래수",  f"{summary['total_trades']}회",    txt_color),
        ("승률",       f"{summary['win_rate']:.1f}%",     green if summary['win_rate'] >= 40 else yellow),
        ("최대 낙폭",  f"-{summary['max_drawdown']:.1f}%", red),
    ]

    for row_i, (label, val, color) in enumerate(metrics):
        y = 0.88 - row_i * 0.155
        ax4.text(0.05, y, label, transform=ax4.transAxes,
                 color='#8b949e', fontsize=10)
        ax4.text(0.97, y, val, transform=ax4.transAxes,
                 color=color, fontsize=11, fontweight='bold', ha='right')
        ax4.plot([0.03, 0.97], [y - 0.06, y - 0.06], color=grid_color,
                 linewidth=0.7, transform=ax4.transAxes)

    ax4.set_title('핵심 지표', color=txt_color, fontsize=11, fontweight='bold', pad=8)

    # ─────────────────────────────────────────────────────────────
    # 5. 연속 손절 분포 (하단 중간)
    # ─────────────────────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[2, 1])
    ax5.set_facecolor(bg_panel)

    results = [t.get('result', '') for t in trades]
    streaks, cur = [], 0
    for r in results:
        if r == 'loss':
            cur += 1
        else:
            if cur > 0:
                streaks.append(cur)
            cur = 0
    if cur > 0:
        streaks.append(cur)

    if streaks:
        max_streak = max(streaks)
        bins = range(1, max_streak + 2)
        n, _, patches = ax5.hist(streaks, bins=bins, color=red, alpha=0.75,
                                  edgecolor=bg_panel, align='left')
        for p, b in zip(patches, bins):
            if b >= 3:
                p.set_color('#ff6b6b')

    ax5.axvline(3, color=yellow, linewidth=1.5, linestyle='--', alpha=0.8, label='쿨다운 임계값(3)')
    ax5.set_title('연속 손절 분포', color=txt_color, fontsize=11, fontweight='bold')
    ax5.set_xlabel('연속 손절 횟수', color=txt_color, fontsize=9)
    ax5.set_ylabel('발생 횟수', color=txt_color, fontsize=9)
    ax5.tick_params(colors=txt_color, labelsize=8)
    ax5.spines[:].set_color(grid_color)
    ax5.grid(color=grid_color, linewidth=0.4, axis='y')
    ax5.legend(fontsize=8, framealpha=0, labelcolor=yellow)

    # ─────────────────────────────────────────────────────────────
    # 6. RR 분포 히스토그램 (하단 오른쪽)
    # ─────────────────────────────────────────────────────────────
    ax6 = fig.add_subplot(gs[2, 2])
    ax6.set_facecolor(bg_panel)

    rrs = [t.get('rr', 0) for t in trades if t.get('rr', 0) > 0]
    if rrs:
        ax6.hist(rrs, bins=12, color=purple, alpha=0.75, edgecolor=bg_panel)
        ax6.axvline(np.mean(rrs), color=yellow, linewidth=1.5, linestyle='--',
                    label=f'평균 RR: {np.mean(rrs):.2f}')
        ax6.axvline(1.5, color=green, linewidth=1, linestyle=':', alpha=0.8, label='최소 RR 1.5')

    ax6.set_title('손익비(RR) 분포', color=txt_color, fontsize=11, fontweight='bold')
    ax6.set_xlabel('RR 비율', color=txt_color, fontsize=9)
    ax6.set_ylabel('거래 수', color=txt_color, fontsize=9)
    ax6.tick_params(colors=txt_color, labelsize=8)
    ax6.spines[:].set_color(grid_color)
    ax6.grid(color=grid_color, linewidth=0.4, axis='y')
    ax6.legend(fontsize=8, framealpha=0, labelcolor=txt_color)

    # ─────────────────────────────────────────────────────────────
    plt.suptitle(
        f"아이린(Irene) 백테스트 리포트  |  {data.get('updated_at', '')}",
        color='#8b949e', fontsize=10, y=0.99
    )

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'backtest_chart.png')
    plt.savefig(out_path, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    print(f"✅ 차트 저장: {out_path}")
    plt.show()

if __name__ == '__main__':
    data = load_data()
    plot_backtest(data)
