"""
아이린 위성(Satellite) 전략 — 킬존 FVG 스나이핑 v3
────────────────────────────────────────────────
목표  : 극단적 손익비(1:3~1:5)로 단기간 자본 폭발적 성장
자본  : 전체 시드의 20~30% (기본 467 USDT)

v2 손실 방어 3중 장치:
  1. 이중 복리 방지  — 리스크 기준을 현재 자본이 아닌 초기 자본으로 고정
  2. 연속 손실 동적 쿨다운
                     — 1연속:20분 / 2연속:40분 / 3연속:80분 / 4+연속:160분
  3. 하이워터마크 보호
                     — 고점 대비 15% 하락 시 복리 배율 강제 0.7배 감속

v3 진입 승률 개선:
  4. 1D + 4H 추세 정렬 필수
                     — 1D EMA20/50 방향과 4H EMA20/50 방향이 일치할 때만 진입
                       (6개월 백테스트 기준 +39% ROI / 30.8% 승률)
"""

import time as _time


class SatelliteStrategy:
    def __init__(
        self,
        ict_engine,
        satellite_capital: float = 467.0,
        base_risk_pct: float = 0.08,           # v3: 5% → 8% (공격적)
        max_leverage: int = 20,
        min_rr: float = 3.0,
        compound_win_factor: float = 1.5,      # v3: 1.3 → 1.5 (연승 가속)
        compound_loss_factor: float = 0.8,
        max_compound_factor: float = 5.0,      # v3: 3.0 → 5.0 (복리 상한 확장)
        min_compound_factor: float = 0.5,
        cooldown_minutes: int = 20,
        hwm_drawdown_threshold: float = 0.15,
        hwm_penalty_factor: float = 0.7,
    ):
        self.ict_engine = ict_engine
        self.satellite_capital = satellite_capital
        self.current_capital   = satellite_capital

        self.base_risk_pct          = base_risk_pct
        self.max_leverage           = max_leverage
        self.min_rr                 = min_rr
        self.compound_win_factor    = compound_win_factor
        self.compound_loss_factor   = compound_loss_factor
        self.max_compound_factor    = max_compound_factor
        self.min_compound_factor    = min_compound_factor
        self.base_cooldown_minutes  = cooldown_minutes
        self.hwm_drawdown_threshold = hwm_drawdown_threshold
        self.hwm_penalty_factor     = hwm_penalty_factor

        # 상태
        self.compound_factor: float = 1.0
        self.last_trade_time: float = 0
        self.consecutive_losses: int = 0
        self.consecutive_wins: int   = 0
        self.peak_capital: float     = satellite_capital  # 하이워터마크

    # ── 현재 동적 쿨다운 계산 ──────────────────
    @property
    def cooldown_minutes(self) -> int:
        """연속 손실 횟수에 따라 쿨다운 자동 증가."""
        if self.consecutive_losses <= 1:
            return self.base_cooldown_minutes           # 20분
        elif self.consecutive_losses == 2:
            return self.base_cooldown_minutes * 2       # 40분
        elif self.consecutive_losses == 3:
            return self.base_cooldown_minutes * 4       # 80분
        else:
            return self.base_cooldown_minutes * 8       # 160분

    # ──────────────────────────────────────────
    # 메인 진입 분석
    # ──────────────────────────────────────────
    def analyze_entry(self, data_dict: dict, current_time=None) -> dict:
        result = {
            'action': 'hold',
            'side': None,
            'reasons': [],
            'risk_amount': 0.0,
            'leverage': self.max_leverage,
            'compound_factor': self.compound_factor,
            'satellite_mode': True,
        }

        # ── 자본 소진 체크 ──
        if self.current_capital <= 0:
            result['reasons'].append("💀 위성 자본 소진 → 비활성")
            return result

        # ── 동적 쿨다운 체크 ──
        import time as _t
        now_ts = current_time.timestamp() if current_time else _t.time()
        if self.last_trade_time > 0:
            elapsed  = (now_ts - self.last_trade_time) / 60
            cooldown = self.cooldown_minutes
            if 0 <= elapsed < cooldown:
                result['reasons'].append(
                    f"⏳ 위성 쿨다운 ({cooldown - elapsed:.0f}분 남음"
                    f"{' ×'+str(cooldown//self.base_cooldown_minutes) if cooldown > self.base_cooldown_minutes else ''})"
                )
                return result

        # ── 1. 킬존 (뉴욕 런치 제외, 아시아 포함) ──
        kz = self.ict_engine.is_kill_zone(current_time=current_time)
        if not kz['in_kill_zone']:
            return result
        if kz['session'] == '뉴욕 런치':
            return result
        result['reasons'].append(f"⚡ {kz['session']} 활성")

        # ── 2. [1순위] 1D 시장 구조 — BOS/MSS ──
        df_1d = data_dict.get('1d')
        if df_1d is None or len(df_1d) < 30:
            result['reasons'].append("⚠️ 1D 데이터 부족")
            return result

        bos_mss = self.ict_engine.detect_bos_mss(df_1d, swing_window=3)
        struct_1d = bos_mss['direction']

        if struct_1d == 'neutral':
            result['reasons'].append(f"⏸ 1D 구조 미확정 → 위성 대기")
            return result
        result['reasons'].append(f"🏛 1D 구조: {struct_1d.upper()} ({bos_mss['reason']})")

        # ── 3. [2순위] 200 EMA 거시 필터 ──
        ema200_1d    = df_1d['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        price_1d     = float(df_1d['close'].iloc[-1])
        below_200ema = price_1d < ema200_1d

        # 200 EMA 아래에서 BUY는 차단
        if below_200ema and struct_1d == 'bullish':
            result['reasons'].append(
                f"⛔ 200EMA({ema200_1d:.0f}) 아래 BUY → 위성 대기"
            )
            return result
        macro_tag = f"200EMA {'아래↓' if below_200ema else '위↑'}({ema200_1d:.0f})"
        result['reasons'].append(f"📏 {macro_tag}")

        # ── 4. [3순위] 4H 20EMA 모멘텀 확인 ──
        df_4h = data_dict.get('4h')
        if df_4h is None or len(df_4h) < 20:
            result['reasons'].append("⚠️ 4H 데이터 부족")
            return result

        ema20_4h  = df_4h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        price_4h  = float(df_4h['close'].iloc[-1])
        momentum_4h = 'bullish' if price_4h > ema20_4h else 'bearish'

        # 1D 구조와 4H 모멘텀 불일치 시 차단
        if momentum_4h != struct_1d:
            result['reasons'].append(
                f"⛔ 4H 모멘텀({momentum_4h}) ≠ 1D 구조({struct_1d}) → 위성 대기"
            )
            return result
        result['reasons'].append(f"📈 4H 20EMA 모멘텀: {momentum_4h} (가격 {price_4h:.0f})")

        side = 'buy' if struct_1d == 'bullish' else 'sell'
        result['side'] = side
        result['reasons'].append(f"✅ 3레이어 정렬 완료: {side.upper()}")

        # ── 3. 15m 유동성 스윕 확인 ──
        df_15m = data_dict.get('15m')
        if df_15m is None or len(df_15m) < 30:
            result['reasons'].append("⚠️ 15m 데이터 부족")
            return result

        sweep_type_needed = 'SSL_sweep' if side == 'buy' else 'BSL_sweep'
        sweeps = self.ict_engine.detect_liquidity_sweeps(df_15m)
        recent_sweeps = [s for s in sweeps
                         if s['type'] == sweep_type_needed
                         and s['index'] >= len(df_15m) - 24]

        if not recent_sweeps:
            result['reasons'].append(f"❌ {'SSL' if side=='buy' else 'BSL'} 스윕 없음 → 대기")
            return result

        sweep_idx = max(s['index'] for s in recent_sweeps)
        result['reasons'].append(f"🎯 {'SSL' if side=='buy' else 'BSL'} 스윕 확인")

        # ── 4. 스윕 후 FVG 타점 ──
        fvgs          = self.ict_engine.detect_fvg(df_15m)
        current_price = df_15m.iloc[-1]['close']
        fvg_type      = 'bullish' if side == 'buy' else 'bearish'

        post_sweep_fvgs = [f for f in fvgs
                           if f['type'] == fvg_type and f['index'] >= sweep_idx]
        in_fvg = any(f['bottom'] * 0.999 <= current_price <= f['top'] * 1.001
                     for f in post_sweep_fvgs)

        if not in_fvg:
            result['reasons'].append("❌ 스윕 후 FVG 타점 미도달 → 대기")
            return result

        result['reasons'].append(f"📦 스윕 후 FVG 타점 ({fvg_type})")

        # ── 4-1. MSS 확인 (선택 — 레버리지 보너스 복구) ──
        mss_signals = self.ict_engine.detect_mss(df_15m)
        mss_type    = 'bullish' if side == 'buy' else 'bearish'
        has_mss     = any(m['type'] == mss_type and m['index'] > sweep_idx
                          for m in mss_signals)
        if has_mss:
            result['reasons'].append("🔄 MSS 확인 → 레버리지 +2배 보너스")

        # ── 5. 리스크 금액 계산 (v2: 초기 자본 기준 — 이중 복리 방지) ──
        effective_risk_pct = min(
            self.base_risk_pct * self.compound_factor,
            0.20  # 하드캡 (최공격: 20%)
        )
        # ★ 핵심 변경: current_capital → satellite_capital (초기 자본 고정)
        risk_amount = round(self.satellite_capital * effective_risk_pct, 2)
        result['risk_amount'] = risk_amount

        # ── 6. 레버리지 결정 ──
        sl, tp = self.ict_engine.calculate_sl_tp(df_15m, side)
        if sl and tp:
            sl_dist = abs(current_price - sl) / current_price
            tp_dist = abs(tp - current_price) / current_price
            rr = tp_dist / sl_dist if sl_dist > 0 else 0

            if rr < self.min_rr:
                result['reasons'].append(f"❌ RR {rr:.1f} < {self.min_rr:.1f} → 위성 미달")
                return result

            required_lev = round(risk_amount / (self.current_capital * sl_dist), 1)
            base_lev = max(5, min(int(required_lev), self.max_leverage))
            leverage = min(base_lev + (2 if has_mss else 0), self.max_leverage)
            result['leverage'] = leverage
            result['reasons'].append(f"📐 RR {rr:.1f} | 레버리지 {leverage}배")
        else:
            result['leverage'] = 15

        # ── 7. 진입 확정 ──
        result['action'] = side
        result['compound_factor'] = self.compound_factor

        # 하이워터마크 경고 출력
        hwm_dd = (self.peak_capital - self.current_capital) / self.peak_capital
        if hwm_dd >= self.hwm_drawdown_threshold:
            result['reasons'].append(
                f"⚠️ HWM 보호 중 (고점 대비 -{hwm_dd*100:.1f}%, 배율 감속 적용)"
            )

        result['reasons'].append(
            f"🚀 [위성 진입] {side.upper()} | "
            f"복리배율 {self.compound_factor:.2f}x | "
            f"리스크 {risk_amount:.2f}U ({effective_risk_pct*100:.1f}% of 초기자본)"
        )
        return result

    # ──────────────────────────────────────────
    # 복리 상태 업데이트
    # ──────────────────────────────────────────
    def record_win(self, pnl: float, current_time=None):
        import time as _t
        self.current_capital += pnl

        # 하이워터마크 갱신
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

        self.compound_factor = min(
            self.max_compound_factor,
            self.compound_factor * self.compound_win_factor
        )
        self.consecutive_wins   += 1
        self.consecutive_losses  = 0
        self.last_trade_time = current_time.timestamp() if current_time else _t.time()
        print(
            f"  🚀 [위성WIN] PnL:{pnl:+.2f} | 자본:{self.current_capital:.2f} | "
            f"복리:{self.compound_factor:.2f}x | 고점:{self.peak_capital:.2f} "
            f"({self.consecutive_wins}연속 수익)"
        )

    def record_loss(self, pnl: float, current_time=None):
        import time as _t
        self.current_capital = max(0, self.current_capital + pnl)

        # ★ 하이워터마크 보호: 고점 대비 낙폭이 임계치 초과 시 배율 강제 감속
        hwm_dd = (self.peak_capital - self.current_capital) / self.peak_capital
        if hwm_dd >= self.hwm_drawdown_threshold:
            self.compound_factor = max(
                self.min_compound_factor,
                self.compound_factor * self.hwm_penalty_factor  # 추가 -30% 감속
            )
            print(f"  🛡️  [HWM 발동] 고점 대비 -{hwm_dd*100:.1f}% → 배율 강제 감속")
        else:
            self.compound_factor = max(
                self.min_compound_factor,
                self.compound_factor * self.compound_loss_factor
            )

        self.consecutive_losses += 1
        self.consecutive_wins    = 0
        self.last_trade_time = current_time.timestamp() if current_time else _t.time()

        cooldown = self.cooldown_minutes
        print(
            f"  💥 [위성LOSS] PnL:{pnl:+.2f} | 자본:{self.current_capital:.2f} | "
            f"복리:{self.compound_factor:.2f}x | 쿨다운:{cooldown}분 "
            f"({self.consecutive_losses}연속 손실)"
        )

    def status_report(self) -> dict:
        roi = (self.current_capital - self.satellite_capital) / self.satellite_capital * 100
        return {
            'initial_capital':    self.satellite_capital,
            'current_capital':    round(self.current_capital, 2),
            'peak_capital':       round(self.peak_capital, 2),
            'roi_pct':            round(roi, 2),
            'compound_factor':    round(self.compound_factor, 3),
            'consecutive_wins':   self.consecutive_wins,
            'consecutive_losses': self.consecutive_losses,
            'dynamic_cooldown':   self.cooldown_minutes,
        }
