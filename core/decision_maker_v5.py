"""
아이린 코어 두뇌 v5
────────────────────────────────────────────────
v5 핵심 변경:
  진입 로직  = 위성 v3와 동일 (1D BOS/MSS + 200EMA + 4H 20EMA + 킬존 + 스윕+FVG)
  포지션 사이징 = 실시간 OI + L/S 비율 기반 가변 리스크 (1% ~ 3%)

외부 데이터 점수 → 리스크:
  BUY  셋업: L/S short_heavy(+1.5) + OI rising(+1.0) 최대 2.5점
  SELL 셋업: L/S long_heavy(+1.5)  + OI rising(+1.0) 최대 2.5점
  score ≥ 2.0 → 3%  |  ≥ 1.0 → 2%  |  < 1.0 → 1%

백테스트 검증 결과:
  위성 v3 (고정 1%): +80.5% ROI / MDD 11.2%
  메인 v5 (실 OI/L/S): +239.2% ROI / MDD 20.0%
"""

import time as _time


class DecisionMakerV5:
    """
    코어 전략 v5 두뇌.
    DecisionMaker와 동일한 인터페이스를 제공하여 BarbellManager와 호환됩니다.
    """

    FIXED_RR      = 3.0
    BASE_RISK_PCT = 0.010   # 최소 리스크
    MAX_RISK_PCT  = 0.030   # 최대 리스크

    def __init__(self, ict_engine, fetcher, cooldown_minutes: int = 30):
        """
        Args:
            ict_engine      : ICTEngine 인스턴스
            fetcher         : DataFetcher 인스턴스 (실시간 OI/L/S 조회용)
            cooldown_minutes: 마지막 거래 후 대기 시간 (분)
        """
        self.ict_engine      = ict_engine
        self.fetcher         = fetcher
        self.cooldown_minutes = cooldown_minutes
        self.last_trade_time  = 0

        # BarbellManager / 대시보드 호환용 더미 속성
        self.min_confluence = 0.0
        self.max_score      = 10.0

    # ──────────────────────────────────────────
    #  실시간 외부 데이터 → 리스크 배율
    # ──────────────────────────────────────────

    def _fetch_ext_score(self, symbol: str, side: str) -> float:
        """
        실시간 OI 변화율 + L/S 비율로 포지션 사이징 점수 계산 (0.0 ~ 2.5).
        API 오류 시 0.0 반환 (기본 1% 리스크).
        """
        score = 0.0
        try:
            oi = self.fetcher.fetch_oi_change_rate(symbol, interval='1h', lookback=6)
            oi_trend = oi.get('trend', 'neutral')
            if oi_trend == 'rising':    score += 1.0
            elif oi_trend == 'neutral': score += 0.3
        except Exception:
            pass

        try:
            ls = self.fetcher.fetch_long_short_history(symbol, period='1h', limit=6)
            ls_bias = ls.get('bias', 'neutral')
            if side == 'buy':
                if ls_bias == 'short_heavy': score += 1.5
                elif ls_bias == 'neutral':   score += 0.5
            else:
                if ls_bias == 'long_heavy':  score += 1.5
                elif ls_bias == 'neutral':   score += 0.5
        except Exception:
            pass

        return round(score, 2)

    def _score_to_risk(self, score: float) -> float:
        if score >= 2.0: return self.MAX_RISK_PCT   # 3%
        if score >= 1.0: return 0.020               # 2%
        return           self.BASE_RISK_PCT          # 1%

    # ──────────────────────────────────────────
    #  핵심 진입 분석
    # ──────────────────────────────────────────

    def analyze_entry(self, data_dict: dict, symbol: str = 'BTC/USDT',
                      current_time=None) -> dict:
        """
        멀티 타임프레임 데이터를 분석하여 진입 신호를 반환합니다.

        Returns dict:
            action     : 'buy' | 'sell' | 'hold'
            side       : 'buy' | 'sell' | None
            confluence : 점수 (호환용, 0.0~5.0)
            risk_pct   : 진입 시 사용할 리스크 비율 (0.01 ~ 0.03)
            reasons    : 판단 근거 리스트
        """
        result = {
            'action':     'hold',
            'side':       None,
            'confluence': 0.0,
            'risk_pct':   self.BASE_RISK_PCT,
            'reasons':    [],
            'scores':     {},
            'god_tier':   {},
        }

        # ── 쿨다운 체크 ──
        now_ts = current_time.timestamp() if current_time else _time.time()
        if self.last_trade_time > 0:
            elapsed = (now_ts - self.last_trade_time) / 60
            if 0 <= elapsed < self.cooldown_minutes:
                result['reasons'].append(
                    f"⏳ 코어 쿨다운 ({self.cooldown_minutes - elapsed:.0f}분 남음)"
                )
                return result

        # ── 1. 킬존 (뉴욕 런치 제외) ──
        kz = self.ict_engine.is_kill_zone(current_time=current_time)
        if not kz['in_kill_zone']:
            return result
        if kz.get('session') == '뉴욕 런치':
            return result
        result['reasons'].append(f"⚡ {kz['session']} 활성")
        result['confluence'] += 0.5

        # ── 2. 1D EMA 200 추세 필터 ──
        df_1d = data_dict.get('1d')
        if df_1d is None or len(df_1d) < 200:
            result['reasons'].append("⚠️ 1D 데이터 부족 (EMA 200 필요)")
            return result
        
        current_price = float(df_1d.iloc[-1]['close'])
        ema_200 = df_1d['close'].ewm(span=200, adjust=False).mean().iloc[-1]
        
        trend_1d = 'bullish' if current_price > ema_200 else 'bearish'
        result['reasons'].append(f"📈 1D EMA200 기준 추세: {trend_1d.upper()}")
        result['confluence'] += 1.0

        # ── 3. 4H EMA 20 모멘텀 필터 ──
        df_4h = data_dict.get('4h')
        if df_4h is None or len(df_4h) < 20:
            result['reasons'].append("⚠️ 4H 데이터 부족 (EMA 20 필요)")
            return result
        
        ema_20_4h = df_4h['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        momentum_4h = 'bullish' if float(df_4h.iloc[-1]['close']) > ema_20_4h else 'bearish'
        
        if trend_1d != momentum_4h:
            result['reasons'].append("⏸ 1D 추세와 4H 모멘텀 불일치 → 대기")
            return result

        result['reasons'].append(f"🚀 4H EMA20 모멘텀 동기화 확인")
        result['confluence'] += 0.5
        
        # ── 4. 방향 설정 ──
        side = trend_1d
        result['side'] = side

        # ── 5. 15m 스윕 + FVG 타점 (스윕 필수) ──
        df_15m = data_dict.get('15m')
        if df_15m is None or len(df_15m) < 30:
            result['reasons'].append("⚠️ 15m 데이터 부족")
            return result

        sweep_type_needed = 'SSL_sweep' if side == 'buy' else 'BSL_sweep'
        sweeps        = self.ict_engine.detect_liquidity_sweeps(df_15m)
        recent_sweeps = [s for s in sweeps
                         if s['type'] == sweep_type_needed
                         and s['index'] >= len(df_15m) - 24]

        if not recent_sweeps:
            result['reasons'].append(f"❌ {'SSL' if side=='buy' else 'BSL'} 스윕 없음 → 대기")
            return result

        result['reasons'].append(f"🎯 {'SSL' if side=='buy' else 'BSL'} 스윕 확인")
        result['confluence'] += 1.0

        sweep_idx = max(s['index'] for s in recent_sweeps)
        current_price = float(df_15m.iloc[-1]['close'])
        fvg_type = 'bullish' if side == 'buy' else 'bearish'
        fvgs = self.ict_engine.detect_fvg(df_15m)
        
        post_sweep_fvgs = [f for f in fvgs
                           if f['type'] == fvg_type and f['index'] >= sweep_idx]

        in_fvg = any(f['bottom'] * 0.999 <= current_price <= f['top'] * 1.001
                     for f in post_sweep_fvgs)

        if not in_fvg:
            result['reasons'].append("❌ 스윕 후 FVG 타점 미도달 → 대기")
            return result

        result['reasons'].append(f"📦 스윕 후 FVG 타점 ({fvg_type})")
        result['confluence'] += 1.0

        # MSS 보너스
        mss_signals = self.ict_engine.detect_mss(df_15m)
        has_mss = any(m['type'] == fvg_type and m['index'] > sweep_idx for m in mss_signals)
        if has_mss:
            result['confluence'] += 0.5
            result['reasons'].append("🔄 MSS 확인 (+0.5)")

        # ── 6. 실시간 OI/L/S → 리스크 배율 ──
        ext_score = self._fetch_ext_score(symbol, side)
        risk_pct  = self._score_to_risk(ext_score)
        result['risk_pct'] = risk_pct

        oi_tag = f"OI/L/S 점수={ext_score:.1f} → 리스크 {risk_pct*100:.0f}%"
        if ext_score >= 2.0:
            result['reasons'].append(f"🔥 {oi_tag} (최고 확신)")
        elif ext_score >= 1.0:
            result['reasons'].append(f"💡 {oi_tag} (확인됨)")
        else:
            result['reasons'].append(f"⚪ {oi_tag} (기본)")

        # ── 최종 진입 결정 ──
        result['action'] = side
        result['reasons'].append(
            f"✅ [v5] 5레이어 완성 | 컨플루언스 {result['confluence']:.1f} | "
            f"RR {self.FIXED_RR}:1 | 리스크 {risk_pct*100:.0f}% → {side.upper()}"
        )
        return result

    # ──────────────────────────────────────────
    #  쿨다운 관리
    # ──────────────────────────────────────────

    def record_trade(self, current_time=None):
        """거래 실행 후 쿨다운 타이머 시작."""
        if current_time:
            self.last_trade_time = (current_time.timestamp()
                                    if hasattr(current_time, 'timestamp')
                                    else float(current_time))
        else:
            self.last_trade_time = _time.time()

    # LTF 스캘프 호환용 (v5에서는 사용 안 함, 인터페이스 유지)
    def record_scalp_trade(self, current_time=None):
        self.record_trade(current_time=current_time)
