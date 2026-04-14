"""
아이린 위성(Satellite) 전략 백테스터 — 최공격 v3
────────────────────────────────────────────────
최공격 3종 세트:
  1. 파라미터 강화  — risk 8%, compound 1.5x, max_compound 5x
  2. 멀티심볼       — BTC + ETH 동시 독립 운용
  3. 피라미딩       — TP 50% 도달 시 추가 진입 + SL → BE

피라미딩 구조:
  진입  P,  SL  S,  TP  T
  H = P + (T-P)*0.5   ← 피라미드 트리거
  피라미드 발동 시:
    - Lot2 추가 진입 @ H
    - SL → P (원래 진입가 = BE)
  TP 도달 시 총 수익:
    Lot1: (T-P)*qty  /  Lot2: (T-H)*qty  =  1.5x 단순 진입 대비
"""

import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from datetime import timedelta

from core.ict_engine import ICTEngine
from core.data_fetcher import DataFetcher
from strategy.satellite import SatelliteStrategy


class SatelliteBacktester:
    def __init__(
        self,
        symbols=None,
        satellite_capital: float = 467.0,
        base_risk_pct: float = 0.08,
        max_leverage: int = 20,
        enable_pyramiding: bool = True,
    ):
        if symbols is None:
            symbols = ['BTC/USDT', 'ETH/USDT']
        self.symbols          = symbols if isinstance(symbols, list) else [symbols]
        self.enable_pyramiding = enable_pyramiding
        self.ict_engine       = ICTEngine()
        self.fetcher          = DataFetcher()

        # 심볼마다 독립적인 전략 인스턴스 (독립 자본 풀)
        self.strategies = {}
        for sym in self.symbols:
            self.strategies[sym] = SatelliteStrategy(
                ict_engine=self.ict_engine,
                satellite_capital=satellite_capital,
                base_risk_pct=base_risk_pct,
                max_leverage=max_leverage,
                min_rr=3.0,
                cooldown_minutes=20,
            )

        self.all_trades = {sym: [] for sym in self.symbols}
        self.equity_curves = {
            sym: [satellite_capital] for sym in self.symbols
        }
        self.satellite_capital = satellite_capital

    # ── 데이터 수집 ──────────────────────────────
    def _fetch(self, symbol: str, limit: int):
        print(f"  📡 {symbol} 데이터 수집 중...")
        limit_4h = int(limit / 16) + 50
        limit_1d = int(limit / 96) + 50
        df_15m = self.fetcher.fetch_ohlcv(symbol, '15m', limit=limit)
        df_4h  = self.fetcher.fetch_ohlcv(symbol, '4h',  limit=limit_4h)
        df_1d  = self.fetcher.fetch_ohlcv(symbol, '1d',  limit=limit_1d)
        if df_15m is None or len(df_15m) < 100:
            print(f"  ❌ {symbol} 데이터 부족"); return None
        print(f"  ✅ {symbol}: 15m({len(df_15m)}), 4h({len(df_4h) if df_4h is not None else 0}), "
              f"1d({len(df_1d) if df_1d is not None else 0})")
        return {'15m': df_15m, '4h': df_4h, '1d': df_1d}

    # ── 단일 심볼 루프 ────────────────────────────
    def _run_symbol(self, symbol: str, limit: int):
        raw = self._fetch(symbol, limit)
        if not raw:
            return

        satellite = self.strategies[symbol]
        trades    = self.all_trades[symbol]
        eq_curve  = self.equity_curves[symbol]

        df_15m     = raw['15m'].copy()
        df_4h_full = raw['4h']
        df_1d_full = raw['1d']

        # 지표 선계산
        df_15m['swing_high']  = df_15m['high'].rolling(5, center=True).max()
        df_15m['swing_low']   = df_15m['low'].rolling(5, center=True).min()
        df_15m['body_size']   = abs(df_15m['close'] - df_15m['open'])
        df_15m['avg_body']    = df_15m['body_size'].rolling(10).mean()
        df_15m['roll_max_20'] = df_15m['high'].shift(1).rolling(20).max()
        df_15m['roll_min_20'] = df_15m['low'].shift(1).rolling(20).min()

        if df_4h_full is not None:
            df_4h_full = df_4h_full.copy()
        if df_1d_full is not None:
            df_1d_full = df_1d_full.copy()

        h4_idx = d1_idx = 0
        current_trade = None

        for i in range(100, len(df_15m)):
            row          = df_15m.iloc[i]
            current_time = row['timestamp']

            # 인덱스 동기화
            while (h4_idx + 1 < len(df_4h_full) and
                   df_4h_full.iloc[h4_idx + 1]['timestamp'] <= current_time):
                h4_idx += 1
            if df_1d_full is not None:
                while (d1_idx + 1 < len(df_1d_full) and
                       df_1d_full.iloc[d1_idx + 1]['timestamp'] <= current_time):
                    d1_idx += 1

            # ── 포지션 보유 중 ──────────────────────
            if current_trade is not None:
                side        = current_trade['side']
                entry_price = current_trade['entry_price']
                sl          = current_trade['sl']
                tp          = current_trade['tp']
                entry_time  = current_trade['entry_time']
                exit_price, exit_type = None, None

                # ── 피라미딩 트리거 (TP 50% 지점) ──
                if self.enable_pyramiding and not current_trade.get('pyramid_done'):
                    half_tp = (entry_price + tp) / 2
                    triggered = (side == 'buy'  and row['high'] >= half_tp) or \
                                (side == 'sell' and row['low']  <= half_tp)
                    if triggered:
                        # 수량 2배, SL → 원래 진입가(BE)
                        current_trade['qty']         *= 2
                        current_trade['sl']           = entry_price   # BE
                        current_trade['pyramid_done'] = True
                        current_trade['pyramid_price']= half_tp
                        print(f"  🔺 [{current_time.strftime('%m-%d %H:%M')}] "
                              f"피라미딩 @ {half_tp:.0f} | SL → BE ({entry_price:.0f}) | "
                              f"qty ×2")

                # SL/TP 체크
                if side == 'buy':
                    if row['low']  <= sl: exit_price, exit_type = sl, 'loss'
                    elif row['high'] >= tp: exit_price, exit_type = tp, 'profit'
                else:
                    if row['high'] >= sl: exit_price, exit_type = sl, 'loss'
                    elif row['low']  <= tp: exit_price, exit_type = tp, 'profit'

                # 타임스탑: 24H
                if exit_price is None:
                    hours_open = (current_time - entry_time).total_seconds() / 3600
                    if hours_open >= 24:
                        exit_price = row['close']
                        exit_type  = 'time_stop'

                if exit_price:
                    qty = current_trade['qty']
                    fee = (entry_price + exit_price) * qty * 0.0006
                    pnl = ((exit_price - entry_price) * qty if side == 'buy'
                           else (entry_price - exit_price) * qty)
                    net_pnl = pnl - fee

                    current_trade.update({
                        'exit_price': exit_price,
                        'exit_time':  current_time,
                        'pnl':        round(net_pnl, 2),
                        'result':     exit_type,
                        'status':     'closed',
                    })

                    is_win = exit_type == 'profit'
                    if is_win:
                        satellite.record_win(net_pnl, current_time=current_time)
                    else:
                        satellite.record_loss(net_pnl, current_time=current_time)

                    eq_curve.append(round(satellite.current_capital, 2))
                    pyramid_tag = ' 🔺피라' if current_trade.get('pyramid_done') else ''
                    emoji = '✅' if is_win else ('⏱' if exit_type == 'time_stop' else '❌')
                    print(f"{emoji}[{symbol[:3]}] [{entry_time.strftime('%m-%d %H:%M')}] "
                          f"{side.upper()}{pyramid_tag} → PnL:{net_pnl:+.2f} | "
                          f"복리:{satellite.compound_factor:.2f}x | "
                          f"자본:{satellite.current_capital:.2f}")
                    current_trade = None
                continue

            # ── 자본 소진 ──
            if satellite.current_capital <= 0:
                print(f"💀 [{symbol}] 자본 소진")
                break

            # ── 신호 분석 ──
            snap_15m = df_15m.iloc[i - 100:i + 1]
            snap_4h  = df_4h_full.iloc[max(0, h4_idx - 99):h4_idx + 1]
            snap_1d  = df_1d_full.iloc[max(0, d1_idx - 49):d1_idx + 1] \
                       if df_1d_full is not None else None
            data_dict = {'15m': snap_15m, '4h': snap_4h, '1d': snap_1d}

            signal = satellite.analyze_entry(data_dict, current_time=current_time)
            if signal['action'] not in ('buy', 'sell'):
                continue

            trade = self._open_trade(signal, row['close'], snap_15m, current_time,
                                     satellite, trades, symbol)
            if trade:
                current_trade = trade

        # 미청산 강제 종료
        if current_trade and current_trade['status'] == 'open':
            last = df_15m.iloc[-1]
            qty  = current_trade['qty']
            ep   = current_trade['entry_price']
            pnl  = ((last['close'] - ep) * qty if current_trade['side'] == 'buy'
                    else (ep - last['close']) * qty)
            fee  = (ep + last['close']) * qty * 0.0006
            net  = pnl - fee
            satellite.current_capital += net
            current_trade.update({
                'exit_price': last['close'], 'exit_time': last['timestamp'],
                'pnl': round(net, 2), 'result': 'forced_exit', 'status': 'closed',
            })
            print(f"⚠️  [{symbol}] 미청산 강제 종료 PnL:{net:+.2f}")

    # ── 진입 오픈 ────────────────────────────────
    def _open_trade(self, signal, entry_price, df_snap, entry_time,
                    satellite, trades, symbol):
        sl, tp = self.ict_engine.calculate_sl_tp(df_snap, signal['side'])
        if not sl or not tp:
            return None

        sl_dist = abs(entry_price - sl) / entry_price
        tp_dist = abs(tp - entry_price) / entry_price

        if not (0.003 <= sl_dist <= 0.030):
            return None

        rr = tp_dist / sl_dist if sl_dist > 0 else 0
        if rr < satellite.min_rr:
            return None

        risk_amount = signal['risk_amount']
        sl_usdt     = abs(entry_price - sl)
        qty         = risk_amount / sl_usdt if sl_usdt > 0 else 0
        if qty <= 0:
            return None

        leverage = signal.get('leverage', 15)
        trade = {
            'symbol': symbol, 'side': signal['side'],
            'entry_price': entry_price, 'sl': sl, 'tp': tp, 'qty': qty,
            'entry_time': entry_time, 'status': 'open',
            'rr': round(rr, 2), 'leverage': leverage,
            'compound_factor': signal['compound_factor'],
            'risk_amount': risk_amount,
            'pyramid_done': False, 'pyramid_price': None,
        }
        trades.append(trade)
        print(f"⚡[{symbol[:3]}] [{entry_time.strftime('%m-%d %H:%M')}] "
              f"{signal['side'].upper()} | 복리:{signal['compound_factor']:.2f}x | "
              f"리스크:{risk_amount:.2f}U | RR:{rr:.1f} | 레버:{leverage}배")
        return trade

    # ── 메인 실행 ────────────────────────────────
    def run(self, limit: int = 8640):
        print(f"\n🚀 위성 최공격 백테스트 시작!")
        print(f"📊 심볼: {' + '.join(self.symbols)}")
        print(f"💰 심볼당 초기 자본: {self.satellite_capital:.2f} USDT")
        print(f"🔺 피라미딩: {'ON' if self.enable_pyramiding else 'OFF'}")
        print("─" * 60)

        for sym in self.symbols:
            print(f"\n{'─'*60}")
            print(f"[{sym}] 백테스트 중...")
            self._run_symbol(sym, limit)

        self._print_results()

    # ── 결과 출력 ────────────────────────────────
    def _print_results(self):
        print("\n" + "═" * 60)
        print("🚀 위성 최공격 백테스트 성과 보고서")
        print("═" * 60)

        total_init = 0
        total_final = 0

        for sym in self.symbols:
            satellite = self.strategies[sym]
            trades    = self.all_trades[sym]
            eq_curve  = self.equity_curves[sym]

            print(f"\n【{sym}】")
            if not trades:
                print("  ❌ 진입 신호 없음"); continue

            df = pd.DataFrame(trades)
            closed = df[df['status'] == 'closed']
            if closed.empty:
                print("  ❌ 종료된 거래 없음"); continue

            wins     = closed[closed['result'] == 'profit']
            losses   = closed[closed['result'].isin(['loss', 'time_stop'])]
            win_rate = len(wins) / len(closed) * 100
            init_cap = satellite.satellite_capital

            # MDD
            peak = init_cap
            mdd  = 0.0
            for e in eq_curve:
                peak = max(peak, e)
                dd   = (peak - e) / peak * 100
                mdd  = max(mdd, dd)

            pyramid_trades = closed[closed['pyramid_done'] == True] if 'pyramid_done' in closed.columns else pd.DataFrame()
            roi = (satellite.current_capital - init_cap) / init_cap * 100

            print(f"  💰 {init_cap:.0f} → {satellite.current_capital:.2f} USDT  ({roi:+.2f}%)")
            print(f"  🎯 {len(closed)}회  승률:{win_rate:.1f}% ({len(wins)}승/{len(losses)}패)")
            if len(wins) > 0 and len(losses) > 0:
                print(f"  ⚖️  평균 손익비: {wins['pnl'].mean() / abs(losses['pnl'].mean()):.2f}")
            print(f"  🔺 피라미딩 발동: {len(pyramid_trades)}건")
            print(f"  📉 MDD: {mdd:.2f}%  |  최종 복리배율: {satellite.compound_factor:.3f}x")

            print(f"\n  거래 내역:")
            for _, t in closed.iterrows():
                emoji  = '✅' if t['result'] == 'profit' else ('⏱' if t['result'] == 'time_stop' else '❌')
                p_tag  = ' 🔺' if t.get('pyramid_done') else ''
                print(f"    {emoji} {t['entry_time'].strftime('%m-%d %H:%M')} "
                      f"{t['side'].upper()} RR{t['rr']}{p_tag} "
                      f"복리{t['compound_factor']:.2f}x → {t['pnl']:+.2f}U")

            total_init  += init_cap
            total_final += satellite.current_capital

        if len(self.symbols) > 1:
            combined_roi = (total_final - total_init) / total_init * 100
            print(f"\n{'═'*60}")
            print(f"💼 전체 통합 결과")
            print(f"  투자: {total_init:.0f} USDT → 최종: {total_final:.2f} USDT")
            print(f"  통합 수익률: {combined_roi:+.2f}%")
        print("═" * 60)


if __name__ == '__main__':
    bt = SatelliteBacktester(
        symbols=['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'BNB/USDT'],
        satellite_capital=467.0,
        base_risk_pct=0.08,
        max_leverage=20,
        enable_pyramiding=True,
    )
    bt.run(limit=8640)  # 6개월
