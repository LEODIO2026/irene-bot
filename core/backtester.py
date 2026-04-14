import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os
import json

# 프로젝트 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ict_engine import ICTEngine
from core.decision_maker import DecisionMaker
from core.data_fetcher import DataFetcher
from execution.risk_manager import RiskManager

class Backtester:
    def __init__(self, symbol='BTC/USDT', initial_balance=1000, risk_per_trade=0.025):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.risk_manager = RiskManager(risk_per_trade=risk_per_trade)
        self.ict_engine = ICTEngine()
        # 전략 튜닝 v4.3: min_confluence 4.0 (4.7은 너무 보수적, 거래 빈도 저조)
        self.decision_maker = DecisionMaker(
            self.ict_engine,
            min_confluence=4.0,
            enable_ltf_scalp=True,
            ltf_scalp_min_confluence=3.5,
            scalp_cooldown_minutes=90,
        )
        self.fetcher = DataFetcher()

        self.trades = []
        self.equity_curve = [initial_balance]

        # ── 리스크 보호 ──
        self.consecutive_losses = 0       # 연속 손절 카운터
        self.loss_cooldown_until = None   # 쿨다운 종료 시각 (datetime)

    def fetch_data(self, limit=2000):
        """백테스트 데이터 수집 (상위 타임프레임 동기화 포함)"""
        print(f"📡 {self.symbol} v3 백테스트 데이터 수집 중 (동기화 모드)...")
        try:
            # 15분봉 기준 비례 계산 (4시간 = 16배, 1일 = 96배)
            limit_4h = int(limit / 16) + 100
            limit_1d = int(limit / 96) + 50

            df_15m = self.fetcher.fetch_ohlcv(self.symbol, '15m', limit=limit)
            
            if df_15m is None or len(df_15m) < 100:
                print(f"⚠️  데이터 부족: 요청({limit}) 대비 실제({len(df_15m) if df_15m is not None else 0})")
                return None

            # 실제 수집된 15분봉의 시간 범위를 기준으로 HTF 데이터 재계산
            start_ts = df_15m.iloc[0]['timestamp']
            
            df_4h = self.fetcher.fetch_ohlcv(self.symbol, '4h', limit=limit_4h)
            df_1d = self.fetcher.fetch_ohlcv(self.symbol, '1d', limit=limit_1d)
            
            print(f"✅ 데이터 동기화 완료: 15m({len(df_15m)}), 4h({len(df_4h) if df_4h is not None else 0}), 1d({len(df_1d) if df_1d is not None else 0})")
            return {'15m': df_15m, '4h': df_4h, '1d': df_1d}
        except Exception as e:
            print(f"❌ 데이터 수집 오류: {e}")
            return None

    def simulate_external_data(self, df_snapshot, htf_bias):
        """
        백테스트용 외부 지표 시뮬레이션 v2.
        RSI·볼륨 패턴·가격 모멘텀을 활용해 실전 점수와 유사하게 추정.
        """
        last_row  = df_snapshot.iloc[-1]
        close     = df_snapshot['close']
        volume    = df_snapshot['volume']
        vol_avg   = volume.tail(20).mean()
        vol_ratio = last_row['volume'] / vol_avg if vol_avg > 0 else 1.0

        # ── RSI 14 계산 ──
        delta = close.diff()
        gain  = delta.clip(lower=0).tail(15).mean()
        loss  = (-delta.clip(upper=0)).tail(15).mean()
        rsi   = 100 - (100 / (1 + gain / loss)) if loss > 0 else 50.0

        # ── 가격 모멘텀 (최근 10봉 기준) ──
        price_ref     = close.iloc[-11] if len(close) >= 11 else close.iloc[0]
        momentum_pct  = (last_row['close'] - price_ref) / price_ref * 100

        # ── OI 시뮬 v2: 볼륨 slope + 가격 모멘텀 조합 ──
        vol_series    = volume.tail(6)
        vol_slope     = (vol_series.iloc[-1] - vol_series.iloc[0]) / (vol_series.iloc[0] + 1)
        mock_oi_chg_pct = round(vol_slope * 3 + momentum_pct * 0.4, 2)
        oi_trend = 'rising' if mock_oi_chg_pct > 1.5 else ('falling' if mock_oi_chg_pct < -1.5 else 'neutral')

        oi_mock = {
            'oi_current':   0,
            'oi_change_pct': mock_oi_chg_pct,
            'trend':  oi_trend,
            'signal': oi_trend,
        }

        # ── L/S 비율 시뮬 v2: RSI 기반 군중 포지셔닝 ──
        # RSI 극단 = 개미 과밀 → 역발상 원리
        if rsi > 65:
            ls_ratio, ls_bias = 1.85, 'long_heavy'   # 롱 극단 과밀
        elif rsi < 35:
            ls_ratio, ls_bias = 0.52, 'short_heavy'  # 숏 극단 과밀
        elif htf_bias == 'bearish':
            ls_ratio, ls_bias = 1.45, 'long_heavy'   # 하락장 개미 여전히 롱
        else:
            ls_ratio, ls_bias = 0.72, 'short_heavy'  # 상승장 개미 겁쟁이 숏
        ls_mock = {'current_ratio': ls_ratio, 'avg_ratio': ls_ratio, 'bias': ls_bias}

        # ── Whale Mock v2: OI + L/S ──
        oi_score = 0.35 if oi_trend == 'rising' else (0.1 if oi_trend == 'neutral' else 0)
        ls_score = 0.15 if (htf_bias == 'bearish' and ls_bias == 'long_heavy') or \
                           (htf_bias == 'bullish' and ls_bias == 'short_heavy') else 0
        whale_mock = {
            'score': round(min(1.0, oi_score + ls_score), 2),
            'reasons': [f"🐙 OI 시뮬({mock_oi_chg_pct:+.1f}%) + L/S {ls_ratio:.2f} (백테스트)"],
            'oi_info': {
                'oi_change_pct': mock_oi_chg_pct, 'oi_trend': oi_trend,
                'ls_ratio': ls_ratio, 'ls_bias': ls_bias
            }
        }

        # ── Smart Money v2: 볼륨 이상 + 캔들 패턴 ──
        body_size = abs(last_row['close'] - last_row['open'])
        avg_body  = close.diff().abs().tail(10).mean()
        big_body  = body_size > avg_body * 1.5
        high_vol  = vol_ratio > 1.5

        sm_score  = 0.0
        sm_intent = 'watching'
        if big_body and high_vol and oi_trend == 'rising':
            sm_score, sm_intent = 0.8, 'absorption'
        elif high_vol and oi_trend == 'rising':
            sm_score, sm_intent = 0.5, 'accumulation'
        elif high_vol or oi_trend == 'rising':
            sm_score, sm_intent = 0.3, 'accumulation'

        sm_mock = {
            'score':      sm_score,
            'intent':     sm_intent,
            'change_pct': mock_oi_chg_pct,
            'reasons':    [f"💎 세력 {sm_intent} ({vol_ratio:.1f}x 볼륨, 가상)"] if sm_score > 0 else []
        }

        # ── Crowd Psychology v2: RSI + L/S 역발상 ──
        crowd_score   = 0.0
        crowd_reasons = []
        if htf_bias == 'bullish':
            if ls_bias == 'short_heavy' and rsi < 45:
                crowd_score = 0.7
                crowd_reasons.append(f"🧠 숏 과밀({ls_ratio:.2f}) + RSI 저점({rsi:.0f}) 역발상 (가상)")
            elif ls_bias == 'short_heavy':
                crowd_score = 0.4
                crowd_reasons.append(f"🧠 숏 과밀({ls_ratio:.2f}) 역발상 (가상)")
        else:  # bearish
            if ls_bias == 'long_heavy' and rsi > 55:
                crowd_score = 0.7
                crowd_reasons.append(f"🧠 롱 과밀({ls_ratio:.2f}) + RSI 고점({rsi:.0f}) 역발상 (가상)")
            elif ls_bias == 'long_heavy':
                crowd_score = 0.4
                crowd_reasons.append(f"🧠 롱 과밀({ls_ratio:.2f}) 역발상 (가상)")

        crowd_mock = {
            'score':   crowd_score,
            'reasons': crowd_reasons,
            'details': {'ls_ratio': ls_ratio, 'rsi': round(rsi, 1), 'ls_bias': ls_bias,
                        'fear_greed': max(0, min(100, int(rsi)))}
        }

        # ── 뉴스 시뮬 v2: 20봉 가격 추세로 매크로 센티멘트 근사 ──
        price_20_ref  = close.iloc[-21] if len(close) >= 21 else close.iloc[0]
        trend_20_pct  = (last_row['close'] - price_20_ref) / price_20_ref * 100
        news_score    = 0.0
        news_reasons  = []
        if htf_bias == 'bullish' and trend_20_pct > 2.5:
            news_score = min(0.5, trend_20_pct * 0.08)
            news_reasons.append(f"📰 단기 상승 추세({trend_20_pct:+.1f}%) 매크로 우호 (가상)")
        elif htf_bias == 'bearish' and trend_20_pct < -2.5:
            news_score = min(0.5, abs(trend_20_pct) * 0.08)
            news_reasons.append(f"📰 단기 하락 추세({trend_20_pct:+.1f}%) 매크로 부정 (가상)")

        news_mock = {
            'score':   round(news_score, 2),
            'reasons': news_reasons,
            'details': {'trend_20_pct': round(trend_20_pct, 2)}
        }

        return {
            'smart_money': sm_mock,
            'crowd':       crowd_mock,
            'whale':       whale_mock,
            'oi':          oi_mock,
            'ls':          ls_mock,
            'news':        news_mock,
        }


    def run(self, limit=2000):
        data = self.fetch_data(limit=limit)
        if not data or data['15m'] is None: return

        df_4h_full = data['4h']
        df_1d_full = data['1d']

        # ── 성능 최적화 1: 지표 선계산 (Vectorized) ──
        if df_4h_full is not None:
            df_4h_full = df_4h_full.copy()
            df_4h_full['ema50'] = df_4h_full['close'].ewm(span=50, adjust=False).mean()
        if df_1d_full is not None:
            df_1d_full = df_1d_full.copy()
            df_1d_full['ema50'] = df_1d_full['close'].ewm(span=50, adjust=False).mean()
        
        # 15분봉 지표 선계산 (ICT 엔진 최적화용)
        df_15m = data['15m'].copy()  # ← 원본 데이터에서 가져오기 (필수!)
        df_15m['swing_high'] = df_15m['high'].rolling(window=5, center=True).max()
        df_15m['swing_low']  = df_15m['low'].rolling(window=5, center=True).min()
        df_15m['body_size']  = abs(df_15m['close'] - df_15m['open'])
        df_15m['avg_body']   = df_15m['body_size'].rolling(window=10).mean()
        df_15m['roll_max_20'] = df_15m['high'].shift(1).rolling(window=20).max()
        df_15m['roll_min_20'] = df_15m['low'].shift(1).rolling(window=20).min()

        print(f"🚀 아이린 v4 백테스트 시작! ({len(df_15m)}봉)")
        print(f"💰 시작 잔고: {self.initial_balance} USDT")
        print("──────────────────────────────────────────────────")

        # ── 성능 최적화 2: 인덱스 매핑 (N^2 필터링 제거) ──
        h4_idx, d1_idx = 0, 0
        current_trade  = None   # 현재 열린 포지션 (한 번에 1개만 허용)

        for i in range(100, len(df_15m)):
            current_row = df_15m.iloc[i]
            current_time = current_row['timestamp']
            
            # 4h, 1d 인덱스 업데이트
            while h4_idx + 1 < len(df_4h_full) and df_4h_full.iloc[h4_idx + 1]['timestamp'] <= current_time:
                h4_idx += 1
            while d1_idx + 1 < len(df_1d_full) and df_1d_full.iloc[d1_idx + 1]['timestamp'] <= current_time:
                d1_idx += 1

            # ── 포지션이 열려있는 경우: SL/TP 체크 ──
            if current_trade is not None:
                side        = current_trade['side']
                sl          = current_trade['sl']
                tp          = current_trade['tp']
                entry_price = current_trade['entry_price']
                entry_time  = current_trade['entry_time']
                exit_price, exit_type = None, None

                if side == 'buy':
                    if current_row['low'] <= sl:    exit_price, exit_type = sl, 'loss'
                    elif current_row['high'] >= tp: exit_price, exit_type = tp, 'profit'
                else:
                    if current_row['high'] >= sl:  exit_price, exit_type = sl, 'loss'
                    elif current_row['low'] <= tp:  exit_price, exit_type = tp, 'profit'

                # ── [v4] 타임스탑: 48시간 내 TP 미도달 시 강제 종료 ──
                if exit_price is None:
                    hours_open = (current_time - entry_time).total_seconds() / 3600
                    if hours_open >= 48:
                        exit_price = current_row['close']
                        exit_type  = 'time_stop'
                        print(f"  ⏱️  [타임스탑] {hours_open:.0f}h 경과 → 강제 종료 @ {exit_price:.0f}")

                if exit_price:
                    qty = current_trade['qty']
                    fee = (entry_price + exit_price) * qty * 0.0006
                    pnl = (exit_price - entry_price) * qty if side == 'buy' else (entry_price - exit_price) * qty
                    net_pnl = pnl - fee
                    self.balance += net_pnl
                    self.equity_curve.append(round(self.balance, 2))
                    current_trade.update({
                        'exit_price': exit_price,
                        'exit_time':  current_time,
                        'pnl':        round(net_pnl, 2),
                        'result':     exit_type,
                        'status':     'closed'
                    })
                    # 스캘프 거래는 스캘프 전용 쿨다운만 업데이트 (메인 쿨다운 오염 방지)
                    if current_trade.get('scalp_mode'):
                        self.decision_maker.record_scalp_trade(current_time=current_time)
                    else:
                        self.decision_maker.record_trade(current_time=current_time)
                    emoji = '✅' if exit_type == 'profit' else '❌'
                    mode_tag = "⚡" if current_trade.get('scalp_mode') else ""
                    print(f"{mode_tag}[{entry_time.strftime('%m-%d %H:%M')}] {side.upper()} 진입 ({current_trade['confluence']:.1f}) -> {emoji} 종료 | PnL: {net_pnl:+.2f}")

                    if exit_type in ('loss', 'time_stop'):
                        self.consecutive_losses += 1
                        # 연속 손절 누적에 따라 쿨다운 증가 (3회: 8h / 5회: 24h / 7회+: 48h)
                        if self.consecutive_losses >= 7:
                            cooldown_h = 48
                        elif self.consecutive_losses >= 5:
                            cooldown_h = 24
                        elif self.consecutive_losses >= 3:
                            cooldown_h = 8
                        else:
                            cooldown_h = 0
                        if cooldown_h > 0:
                            self.loss_cooldown_until = current_time + timedelta(hours=cooldown_h)
                            print(f"  ⛔ [리스크] {self.consecutive_losses}연속 손절 → {cooldown_h}시간 쿨다운 (until {self.loss_cooldown_until.strftime('%m-%d %H:%M')})")
                    else:
                        self.consecutive_losses = 0

                    current_trade = None
                continue  # 포지션 중에는 진입 시도 안 함

            # ── 연속 손절 쿨다운 체크 ──
            if self.loss_cooldown_until and current_time < self.loss_cooldown_until:
                continue

            # ── 포지션 없음: 진입 신호 분석 ──
            snapshot_15m = df_15m.iloc[i-100:i+1]
            snapshot_4h  = df_4h_full.iloc[max(0, h4_idx-99):h4_idx+1]
            snapshot_1d  = df_1d_full.iloc[max(0, d1_idx-59):d1_idx+1]

            if not snapshot_4h.empty:
                last_h4 = snapshot_4h.iloc[-1]
                htf_bias = 'bullish' if last_h4['close'] >= last_h4['ema50'] else 'bearish'
            else:
                htf_bias = 'bullish'

            mock_external = self.simulate_external_data(snapshot_15m, htf_bias)
            data_dict = {'15m': snapshot_15m, '4h': snapshot_4h, '1d': snapshot_1d, 'mock_external': mock_external}

            analysis = self.decision_maker.analyze_entry(data_dict, symbol=self.symbol, current_time=current_time)

            if analysis['action'] in ['buy', 'sell']:
                # ── 4H RSI 극단 필터 ──
                h4_rsi = self._calc_rsi(snapshot_4h['close'], period=14) if len(snapshot_4h) >= 15 else 50.0
                # RSI 과매도 반등 구간에서 SELL 차단 (임계값 25→35: dead-cat bounce 방어)
                if analysis['action'] == 'sell' and h4_rsi < 35:
                    pass
                elif analysis['action'] == 'buy' and h4_rsi > 75:
                    pass
                elif not self.ict_engine.is_kill_zone(current_time=current_time)['in_kill_zone'] and analysis['confluence'] < self.decision_maker.min_confluence + 0.5:
                    pass
                # ── [v4] 4H 모멘텀 필터 ──
                elif len(snapshot_4h) >= 20 and not self._check_4h_momentum(snapshot_4h, analysis['action']):
                    pass
                else:
                    current_trade = self.open_trade(analysis['action'], current_row['close'], snapshot_15m, current_time, analysis)
            elif analysis['confluence'] >= 2.0:
                print(f"  🔍 [DEBUG] {current_time.strftime('%m-%d %H:%M')} 점수 미달: {analysis['confluence']:.1f}/{self.decision_maker.min_confluence} | 사유: {analysis['reasons'][-1]}")

        # ── 루프 종료: 미청산 포지션 강제 종료 ──
        if current_trade and current_trade['status'] == 'open':
            last_price  = df_15m.iloc[-1]['close']
            last_time   = df_15m.iloc[-1]['timestamp']
            qty         = current_trade['qty']
            entry_price = current_trade['entry_price']
            pnl = (last_price - entry_price) * qty if current_trade['side'] == 'buy' else (entry_price - last_price) * qty
            fee = (entry_price + last_price) * qty * 0.0006
            net_pnl = pnl - fee
            self.balance += net_pnl
            self.equity_curve.append(round(self.balance, 2))
            current_trade.update({
                'exit_price': last_price,
                'exit_time':  last_time,
                'pnl':        round(net_pnl, 2),
                'result':     'forced_exit',
                'status':     'closed'
            })
            print(f"⚠️  [마침] {current_trade['side'].upper()} 미청산 포지션 강제 종료 (PnL: {net_pnl:+.2f})")

        self.print_results()
        return self.save_results_to_json()

    @staticmethod
    def _calc_rsi(close_series, period=14):
        """RSI 계산 헬퍼"""
        delta = close_series.diff()
        gain = delta.clip(lower=0).tail(period + 1).mean()
        loss = (-delta.clip(upper=0)).tail(period + 1).mean()
        return 100 - (100 / (1 + gain / loss)) if loss > 0 else 50.0

    @staticmethod
    def _check_4h_momentum(df_4h, action):
        """4H EMA20 대비 현재 종가 위치로 단기 모멘텀 확인.
        - BUY: 현재가 > EMA20
        - SELL: 현재가 < EMA20
        """
        if len(df_4h) < 20:
            return True
        ema20 = df_4h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        current_close = df_4h['close'].iloc[-1]
        if action == 'buy':
            return current_close > ema20
        else:
            return current_close < ema20

    FIXED_RR = 3.0  # v4.3: 가변 RR → 고정 3:1 (위성 v3과 동일)

    def open_trade(self, side, entry_price, df_snapshot, entry_time, analysis):
        """
        진입 시그널 발생 시 포지션을 열고 dict를 반환합니다. (1개만 허용)
        v4.3: RR 고정 3:1 — SL은 ICT FVG/OB 기준, TP = entry ± SL거리×3
        """
        sl, _tp_unused = self.ict_engine.calculate_sl_tp(df_snapshot, side)
        if not sl: return None

        sl_dist = abs(entry_price - sl) / entry_price
        if sl_dist == 0: return None

        # ── SL 거리 범위 0.15%~3.0% (위성 v3과 동일) ──
        if not (0.0015 <= sl_dist <= 0.030):
            return None

        # ── TP: 고정 RR 3:1 ──
        if side == 'buy':
            tp = entry_price + (entry_price - sl) * self.FIXED_RR
        else:
            tp = entry_price - (sl - entry_price) * self.FIXED_RR

        tp_dist = abs(tp - entry_price) / entry_price
        rr = self.FIXED_RR

        risk_report = self.risk_manager.calculate_position_size(self.balance, entry_price, sl)
        qty = risk_report['position_qty']
        if qty <= 0: return None

        # ── LTF 스캘프 모드: 포지션 사이즈 50% 축소 ──
        scalp_mode = analysis.get('scalp_mode', False)
        risk_multiplier = analysis.get('risk_multiplier', 1.0)
        if scalp_mode:
            qty *= risk_multiplier

        trade = {
            'side': side, 'entry_price': entry_price, 'sl': sl, 'tp': tp,
            'qty': qty, 'entry_time': entry_time, 'status': 'open',
            'confluence': analysis['confluence'], 'rr': rr,
            'scalp_mode': scalp_mode,
        }
        self.trades.append(trade)
        mode_tag = "⚡스캘프(50%)" if scalp_mode else "🟢"
        print(f"{mode_tag} [{entry_time.strftime('%m-%d %H:%M')}] {side.upper()} 진입 | 점수:{analysis['confluence']:.1f} | SL:{sl:.0f}({sl_dist*100:.2f}%) TP:{tp:.0f}({tp_dist*100:.2f}%) RR:{rr:.1f}")
        return trade

    def print_results(self):
        print("\n" + "═"*60)
        print("🏆 아이린 v4.1 '절대신급 + LTF스캘프' 백테스트 성과 보고서")
        print("═"*60)
        if not self.trades:
            print("❌ 진입 신호 없음"); return

        df = pd.DataFrame(self.trades)
        wins = len(df[df['result'] == 'profit'])
        win_rate = (wins / len(df)) * 100
        roi = ((self.balance - self.initial_balance) / self.initial_balance) * 100

        print(f"💰 수익률: {roi:+.2f}% ({self.balance - self.initial_balance:,.2f} USDT)")
        print(f"🎯 총 거래: {len(df)}회 | 승률: {win_rate:.2f}%")

        win_trades  = df[df['result'] == 'profit']
        loss_trades = df[df['result'] == 'loss']
        if len(loss_trades) > 0 and len(win_trades) > 0:
            avg_win  = win_trades['pnl'].mean()
            avg_loss = abs(loss_trades['pnl'].mean())
            print(f"⚖️ 평균 손익비: {avg_win/avg_loss:.2f}")

        # ── LTF 스캘프 거래 별도 통계 ──
        if 'scalp_mode' in df.columns:
            df_scalp  = df[df['scalp_mode'] == True]
            df_normal = df[df['scalp_mode'] != True]
            if len(df_scalp) > 0:
                print("─" * 40)
                s_wins = len(df_scalp[df_scalp['result'] == 'profit'])
                s_wr   = s_wins / len(df_scalp) * 100
                s_pnl  = df_scalp['pnl'].sum() if 'pnl' in df_scalp.columns else 0
                print(f"⚡ [스캘프] {len(df_scalp)}회 | 승률:{s_wr:.1f}% | PnL합계:{s_pnl:+.2f}")
            if len(df_normal) > 0:
                n_wins = len(df_normal[df_normal['result'] == 'profit'])
                n_wr   = n_wins / len(df_normal) * 100
                n_pnl  = df_normal['pnl'].sum() if 'pnl' in df_normal.columns else 0
                print(f"🟢 [일반]  {len(df_normal)}회 | 승률:{n_wr:.1f}% | PnL합계:{n_pnl:+.2f}")

    def save_results_to_json(self):
        """백테스트 결과를 대시보드용 JSON으로 저장"""
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(root_dir, 'data')
        
        # 권한 부여 및 디렉토리 생성
        if not os.path.exists(data_dir):
            try:
                os.makedirs(data_dir, mode=0o777, exist_ok=True)
            except: pass
            
        file_path = os.path.join(data_dir, 'backtest_latest.json')
        
        # 성적 계산
        total_pnl = sum(t.get('pnl', 0) for t in self.trades)
        win_trades  = [t for t in self.trades if t.get('result') == 'profit']
        loss_trades = [t for t in self.trades if t.get('result') == 'loss']
        win_rate = (len(win_trades) / len(self.trades) * 100) if self.trades else 0
        roi = (total_pnl / self.initial_balance) * 100
        
        # MDD 계산
        drawdown = []
        max_equity = self.initial_balance
        for e in self.equity_curve:
            max_equity = max(max_equity, e)
            drawdown.append((max_equity - e) / max_equity * 100)
        max_drawdown = max(drawdown) if drawdown else 0

        # JSON용 직렬화
        serialized_trades = []
        for t in self.trades:
            st = t.copy()
            st['entry_price'] = round(st['entry_price'], 2)
            if 'exit_price' in st: st['exit_price'] = round(st['exit_price'], 2)
            st['entry_time'] = st['entry_time'].strftime('%Y-%m-%d %H:%M') if hasattr(st['entry_time'], 'strftime') else str(st['entry_time'])
            if 'exit_time' in st:
                st['exit_time'] = st['exit_time'].strftime('%Y-%m-%d %H:%M') if hasattr(st['exit_time'], 'strftime') else str(st['exit_time'])
            serialized_trades.append(st)

        report = {
            'symbol': self.symbol,
            'summary': {
                'total_trades': len(self.trades),
                'win_trades': len(win_trades),
                'loss_trades': len(loss_trades),
                'win_rate': round(win_rate, 2),
                'net_profit': round(total_pnl, 2),
                'roi': round(roi, 2),
                'max_drawdown': round(max_drawdown, 2),
                'final_balance': round(self.balance, 2)
            },
            'equity_curve': self.equity_curve,
            'trades': serialized_trades,
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=4, ensure_ascii=False)
            os.chmod(file_path, 0o666)
            print(f"✅ 대시보드 연동용 JSON 저장 완료: {file_path}")
        except Exception as e:
            print(f"❌ 결과 저장 오류: {e}")

        return {
            'total_return_pct': round(roi, 2),
            'total_trades':     len(self.trades),
            'win_rate':         round(win_rate, 2),
            'avg_rr':           round(sum(t.get('rr',0) for t in self.trades) / max(1, len(self.trades)), 2),
            'max_drawdown':     round(max_drawdown, 2),
            'final_balance':    round(self.balance, 2),
        }

def run_multi_symbol(symbols=None, initial_balance=1000, risk_per_trade=0.02, limit=34560):
    """
    멀티심볼 백테스트: 자본을 균등 분배하여 각 심볼 독립 실행 후 합산.
    symbols 예시: ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    """
    if symbols is None:
        symbols = ['BTC/USDT', 'ETH/USDT']

    per_balance = initial_balance / len(symbols)
    print(f"\n{'═'*60}")
    print(f"🌐 멀티심볼 백테스트: {symbols}")
    print(f"💰 총 자본: {initial_balance} USDT (심볼당 {per_balance:.0f} USDT)")
    print(f"{'═'*60}\n")

    all_trades  = []
    total_final = 0.0
    symbol_results = {}

    for sym in symbols:
        print(f"\n{'─'*40}\n▶ {sym} 백테스트\n{'─'*40}")
        bt = Backtester(symbol=sym, initial_balance=per_balance, risk_per_trade=risk_per_trade)
        res = bt.run(limit=limit)
        total_final += bt.balance
        all_trades.extend(bt.trades)
        symbol_results[sym] = res
        print(f"  → {sym}: {res['total_return_pct']:+.2f}% | {res['total_trades']}회 | 승률 {res['win_rate']:.1f}%")

    total_roi = (total_final - initial_balance) / initial_balance * 100
    wins = sum(1 for t in all_trades if t.get('result') == 'profit')
    total_wr = wins / len(all_trades) * 100 if all_trades else 0

    print(f"\n{'═'*60}")
    print(f"🏆 멀티심볼 합산 결과")
    print(f"  💰 총 수익률: {total_roi:+.2f}%  ({total_final - initial_balance:+.2f} USDT)")
    print(f"  🎯 총 거래: {len(all_trades)}회 | 합산 승률: {total_wr:.1f}%")
    print(f"  💵 최종 잔고: {total_final:.2f} USDT")
    print(f"{'═'*60}\n")
    return symbol_results


if __name__ == "__main__":
    Backtester(symbol='BTC/USDT', initial_balance=1000).run(limit=34560)
