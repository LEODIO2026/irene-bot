"""
아이린(Irene) ICT 컨플루언스 기반 자율 매매 두뇌 v4.1 (절대신급 + LTF 스캘프 모드)
────────────────────────────────────────────────
v4.1 업그레이드:
- LTF 스캘프 모드: 4H ≠ 1D 타임프레임 불일치 시에도
  15m 스윕 → MSS(강한 변위) → POI 3단 시퀀스 확인 시 반 사이즈로 단기 진입
- 스캘프 전용 쿨다운(scalp_cooldown_minutes) 별도 관리 (메인 쿨다운과 독립)
- 스캘프 진입 시 risk_multiplier=0.5 플래그 반환 → 포지션 50% 축소

v4 업그레이드:
- ADX 횡보장 필터: ADX < 20 → 진입 전면 차단
- EQH/EQL 유동성 풀 감지: 기관 유동성 집적 구간 +1.0점
- 점수 체계 유지: 10.0 만점 / 최소 진입 5.0
- 컨플루언스 기반 가변 포지션: 점수→리스크 배율 반환
"""

import time


class DecisionMaker:
    def __init__(self, ict_engine, min_confluence=5.0, cooldown_minutes=30,
                 crowd_engine=None, smart_money=None, whale_detector=None, news_sensor=None,
                 enable_ltf_scalp=False, ltf_scalp_min_confluence=3.5, scalp_cooldown_minutes=90):
        """
        Args:
            ict_engine: ICTEngine 인스턴스
            min_confluence: 최소 컨플루언스 점수 (10.0 만점, 기본 5.0)
            cooldown_minutes: 마지막 거래 후 대기 시간 (분)
            crowd_engine: CrowdPsychologyEngine (군중 심리)
            smart_money: SmartMoneyTracker (스마트 머니 추적)
            whale_detector: WhaleManipulationDetector (세력 감지)
            news_sensor: MacroNewsSensor (매크로 뉴스)
            enable_ltf_scalp: 4H≠1D 불일치 시 LTF 스캘프 모드 활성화 여부
            ltf_scalp_min_confluence: 스캘프 진입 최소 컨플루언스 (기본 3.5)
            scalp_cooldown_minutes: 스캘프 전용 쿨다운 (분, 기본 90)
        """
        self.ict_engine = ict_engine
        self.min_confluence = min_confluence
        self.cooldown_minutes = cooldown_minutes
        self.last_trade_time = 0       # 일반 거래 마지막 시각 (timestamp)
        self.last_scalp_trade_time = 0 # 스캘프 거래 마지막 시각 (timestamp, 독립 관리)
        self.max_score = 10.0          # v3 만점 (ICT 6.0 + 신급 4.0)

        # ── LTF 스캘프 모드 설정 ──
        self.enable_ltf_scalp = enable_ltf_scalp
        self.ltf_scalp_min_confluence = ltf_scalp_min_confluence
        self.scalp_cooldown_minutes = scalp_cooldown_minutes

        # ── v3 신급 모듈 ──
        self.crowd_engine = crowd_engine
        self.smart_money = smart_money
        self.whale_detector = whale_detector
        self.news_sensor = news_sensor

    def determine_htf_bias(self, df_htf):
        """
        상위 타임프레임(4H/1D)의 추세 방향을 순수 ICT 관점(시장 구조)으로 판단합니다.
        후행성 보조지표(EMA 등)를 배제하고 피벗 고점/저점 기반의 BOS/MSS 및 통제권(HH/HL)을 확인합니다.
        """
        if df_htf is None or len(df_htf) < 30:
            return 'neutral'

        # 1. 스윙 구조(HH/HL/LH/LL) 우선 확인
        swing = self.ict_engine.detect_swing_structure(df_htf, swing_window=5, lookback=3)
        
        # 2. 직전 BOS / MSS 구조 이탈(Break) 확인
        bos = self.ict_engine.detect_bos_mss(df_htf, swing_window=3)
        
        # 구조가 명확하게 확장(HH/HL or LH/LL) 중이라면 스윙 구조를 따름
        if swing['structure'] != 'sideways':
            return swing['structure']
            
        # 명확한 확장이 진행 중이지 않다면 가장 최근에 돌파/이탈된 주요 방향을 따름
        if bos['direction'] != 'neutral':
            return bos['direction']
            
        return 'neutral'


    def analyze_entry(self, data_dict, symbol='BTC/USDT', current_time=None):
        """
        멀티 타임프레임 데이터를 종합 분석하여 진입 신호를 생성합니다.
        v3_optimized: 10.0 만점 체계 (ICT 7.0 + 신급 3.0)
        """
        result = {
            'action': 'hold',
            'confluence': 0,
            'reasons': [],
            'side': None,
            'god_tier': {},
            'scores': {} # 0~100 수치 데이터
        }

        # ── 쿨다운 체크 (백테스트 시간축 고려) ──
        import time as _time
        now_ts = current_time.timestamp() if current_time else _time.time()
        
        if self.last_trade_time > 0:
            elapsed = (now_ts - self.last_trade_time) / 60
            # 백테스트 중 과거 데이터는 last_trade_time보다 커야 하며, 쿨다운 기간보다는 길어야 함
            if 0 <= elapsed < self.cooldown_minutes:
                result['reasons'].append(f"쿨다운 중 (남은 시간: {self.cooldown_minutes - elapsed:.0f}분)")
                return result

        df_htf = data_dict.get('1d')
        if df_htf is None:
            df_htf = data_dict.get('4h')
        
        df_4h = data_dict.get('4h')
        df_ltf = data_dict.get('15m')

        if df_htf is None:
            result['reasons'].append("상위 타임프레임 데이터 없음")
            return result

        # 0. ADX 수집 (로깅용, 점수에 영향 없음)
        df_4h_for_adx = data_dict.get('4h')
        adx_val = 25.0
        if df_4h_for_adx is not None and len(df_4h_for_adx) >= 30:
            adx_val = self.ict_engine._calc_adx(df_4h_for_adx, period=14)
        result['scores']['adx'] = round(adx_val, 1)

        # 1. 킬존 체크 (+0.5)
        kz = self.ict_engine.is_kill_zone(current_time=current_time)
        if kz['in_kill_zone']:
            val = kz['weight'] + 0.2  # 킬존 가중치 보강 (+0.2)
            result['confluence'] += val
            result['reasons'].append(f"🕐 {kz['session']} 활성 (+{val:.1f})")
            result['scores']['kill_zone'] = val * 100 # 1.0 기준 (0.7점 = 70%)
        else:
            result['scores']['kill_zone'] = 0

        # 2. 바이어스 확정 (+1.0) — 1D + 4H 동시 일치 필수
        df_4h_data = data_dict.get('4h')
        df_1d_data = data_dict.get('1d')
        bias_4h = self.determine_htf_bias(df_4h_data) if df_4h_data is not None and len(df_4h_data) >= 30 else 'neutral'
        bias_1d = self.determine_htf_bias(df_1d_data) if df_1d_data is not None and len(df_1d_data) >= 30 else 'neutral'

        if bias_4h == 'neutral' or bias_1d == 'neutral':
            result['reasons'].append(f"⏸ 바이어스 중립 (4H:{bias_4h}, 1D:{bias_1d}) → 홀드")
            return result
        if bias_4h != bias_1d:
            # ── LTF 스캘프 모드: 불일치 시에도 15m 세팅이 완성되면 반 사이즈 진입 ──
            if self.enable_ltf_scalp and df_ltf is not None:
                return self._analyze_ltf_scalp(df_ltf, bias_4h, bias_1d, current_time, now_ts)
            result['reasons'].append(f"⏸ 타임프레임 불일치 (4H:{bias_4h} ≠ 1D:{bias_1d}) → 홀드")
            return result

        htf_bias = bias_4h
        side = 'buy' if htf_bias == 'bullish' else 'sell'
        result['side'] = side
        result['confluence'] += 1.0
        result['reasons'].append(f"📈 바이어스 일치: 4H+1D {htf_bias} (+1.0)")
        result['scores']['htf'] = 100

        # 3. 최적 되돌림 (P/D 존 또는 OTE) (+1.0)
        pd_zone = self.ict_engine.detect_premium_discount(df_4h if df_4h is not None else df_htf)
        ote = self.ict_engine.detect_ote_zone(df_ltf) if df_ltf is not None else {'in_ote': False}
        
        pd_score = 0
        if side == 'buy' and pd_zone.get('zone') == 'discount': pd_score = 100
        elif side == 'sell' and pd_zone.get('zone') == 'premium': pd_score = 100
        result['scores']['pd'] = pd_score

        ote_score = 0
        if ote.get('in_ote') and ote.get('direction') == side: ote_score = 100
        result['scores']['ote'] = ote_score

        if pd_score > 0 or ote_score > 0:
            result['confluence'] += 1.0
            result['reasons'].append("💰 최적 되돌림 구간 지지(PD/OTE) (+1.0)")

        # 4. 4H 구조 분석 (+0.5)
        structure_4h = self.ict_engine.analyze_4h_structure(df_4h, htf_bias)
        if structure_4h['has_4h_ob'] or structure_4h['has_4h_fvg']:
            result['confluence'] += 0.5
            result['reasons'].append(f"🏗️ 4H 레벨 타점({structure_4h['details']}) (+0.5)")
            result['scores']['structure_4h'] = 50 # 0.5점 = 50%
        else:
            result['scores']['structure_4h'] = 0

        # 5~7. 하위 타임프레임(15m): 스윕 → MSS(강한 변위) → POI 시퀀스 검증
        result['scores']['sweep'] = 0
        result['scores']['mss'] = 0
        result['scores']['poi'] = 0

        is_sweep_detected = False
        has_mss = False
        has_poi = False
        sweep_idx = -1
        mss_idx = -1
        mss_signals = []

        if df_ltf is not None and len(df_ltf) >= 30:
            sweeps = self.ict_engine.detect_liquidity_sweeps(df_ltf)
            recent_sweeps = [s for s in sweeps if s['index'] >= len(df_ltf) - 12]

            # 5. 스윕 탐지 (필수 조건 1)
            sweep_type_needed = 'SSL_sweep' if side == 'buy' else 'BSL_sweep'
            matching_sweeps = [s for s in recent_sweeps if s['type'] == sweep_type_needed]
            if matching_sweeps:
                is_sweep_detected = True
                sweep_idx = max(s['index'] for s in matching_sweeps)
                label = "SSL" if side == 'buy' else "BSL"
                result['confluence'] += 1.0
                result['reasons'].append(f"🎯 {label} 유동성 사냥 (+1.0)")
                result['scores']['sweep'] = 100

            # 6. MSS + 강한 변위 (필수 조건 2: 스윕 이후 발생 + 변위 강도 필수)
            if is_sweep_detected:
                mss_signals = self.ict_engine.detect_mss(df_ltf)
                mss_type_needed = 'bullish' if side == 'buy' else 'bearish'
                # 스윕보다 이후 인덱스이고 최근 12봉 이내인 MSS만 유효
                post_sweep_mss = [m for m in mss_signals
                                  if m['type'] == mss_type_needed
                                  and m['index'] > sweep_idx
                                  and m['index'] >= len(df_ltf) - 12]

                if post_sweep_mss:
                    disp = self.ict_engine.calculate_displacement_strength(df_ltf, post_sweep_mss)
                    if any(d['is_strong'] for d in disp):
                        has_mss = True
                        mss_idx = max(m['index'] for m in post_sweep_mss)
                        result['confluence'] += 1.5  # MSS + 강한 변위 통합
                        result['reasons'].append("🔄 MSS + 강한 변위 확인 (+1.5)")
                        result['scores']['mss'] = 100
                    else:
                        result['reasons'].append("⚠️ MSS 감지됐으나 변위 약함 → 무효")
                else:
                    result['reasons'].append("⚠️ 스윕 이후 MSS 미감지")

            # 7. POI (타점 조건: 진입 방향과 일치하는 FVG/OB에 현재가 위치하는지 단독 확인 - MSS 종속 아님)
            fvgs = self.ict_engine.detect_fvg(df_ltf)
            current_price = df_ltf.iloc[-1]['close']
            
            has_fvg = False
            if side == 'buy':
                has_fvg = any(f['bottom']*0.998 <= current_price <= f['top']*1.002
                              for f in fvgs if f['type'] == 'bullish' and f['index'] >= len(df_ltf) - 20)
            else:
                has_fvg = any(f['bottom']*0.998 <= current_price <= f['top']*1.002
                              for f in fvgs if f['type'] == 'bearish' and f['index'] >= len(df_ltf) - 20)
            
            if has_fvg:
                has_poi = True
                result['confluence'] += 1.5
                result['reasons'].append("🎯 FVG 타점 도달 (+1.5)")
                result['scores']['poi'] = 100
            else:
                result['reasons'].append("⚠️ 현재가 부근 FVG/POI 미감지")

        # ── [v4] EQH/EQL: 점수 보너스 제거 → TP/SL 정밀화에만 활용 (메타데이터로만 저장) ──
        if df_ltf is not None and len(df_ltf) >= 20:
            eqhl = self.ict_engine.detect_eqh_eql(df_ltf, lookback=40)
            result['scores']['eqhl'] = 0
            result['god_tier']['eqhl'] = eqhl  # 대시보드/SL-TP 계산에 활용
        else:
            result['scores']['eqhl'] = 0

        # ── [v3] 신급 모듈 보너스 (최대 3.0점) ──
        # 백테스트 모드 체크: data_dict에 'mock_external'이 있으면 해당 데이터를 사용함
        mock_data = data_dict.get('mock_external')

        # 백테스트 모드: 모듈이 없어도 mock_data가 있으면 점수 반영
        if self.smart_money or (mock_data and 'smart_money' in mock_data):
            try:
                if mock_data and 'smart_money' in mock_data:
                    sm = mock_data['smart_money']
                else:
                    sm = self.smart_money.analyze(symbol, data_dict, htf_bias, is_ict_sweep=is_sweep_detected)

                sm_score = sm.get('score', 0)
                result['confluence'] += sm_score
                for r in sm.get('reasons', []): result['reasons'].append(r)
                result['scores']['smart_money'] = sm_score * 100
                result['god_tier']['smart_money'] = sm
            except Exception as e:
                print(f"아이린: 스마트머니 분석 오류: {e}")
                result['scores']['smart_money'] = 0

        if self.crowd_engine or (mock_data and 'crowd' in mock_data):
            try:
                if mock_data and 'crowd' in mock_data:
                    crowd = mock_data['crowd']
                else:
                    crowd = self.crowd_engine.analyze(symbol, htf_bias)

                c_score = crowd.get('score', 0)
                result['confluence'] += c_score
                for r in crowd.get('reasons', []): result['reasons'].append(r)
                result['scores']['crowd'] = c_score * 100
                result['god_tier']['crowd'] = crowd
            except: result['scores']['crowd'] = 0

        if self.whale_detector or (mock_data and 'whale' in mock_data):
            try:
                if mock_data and 'whale' in mock_data:
                    whale = mock_data['whale']
                else:
                    fetcher = getattr(self.whale_detector, 'fetcher', None)
                    oi_data = fetcher.fetch_oi_change_rate(symbol) if fetcher else None
                    ls_data = fetcher.fetch_long_short_history(symbol) if fetcher else None
                    whale = self.whale_detector.analyze(
                        data_dict, htf_bias,
                        symbol=symbol, oi_data=oi_data, ls_data=ls_data
                    )

                w_score = min(1.0, whale['score'])
                result['confluence'] += w_score
                if w_score > 0:
                    for r in whale['reasons']: result['reasons'].append(r)
                result['scores']['whale'] = w_score * 100
                result['god_tier']['whale'] = whale
            except Exception as e:
                print(f"아이린: 세력 감지 오류: {e}")
                result['scores']['whale'] = 0

        news_src = mock_data.get('news') if mock_data else None
        if news_src or self.news_sensor:
            try:
                # 📰 매크로 뉴스 (최대 0.5) — 백테스트 시 mock 데이터 우선 사용
                if news_src:
                    news = news_src
                else:
                    news = self.news_sensor.analyze(htf_bias)
                n_score = min(0.5, news['score'])
                result['confluence'] += n_score
                if n_score > 0:
                    for r in news['reasons']: result['reasons'].append(r)
                result['scores']['news'] = n_score * 200  # 0.5점 = 100%
                result['god_tier']['news'] = news
            except: result['scores']['news'] = 0

        # ── 최종 판별 (v4 - ICT 완화 모드) ──
        result.pop('_weak_trend', None)
        effective_min = self.min_confluence

        ict_conditions_met = sum([is_sweep_detected, has_mss, has_poi])

        if not has_poi:
            result['action'] = 'hold'
            result['reasons'].append(f"⏸ [ICT 게이트키퍼] FVG 타점 형성이 필요합니다 (스윕/MSS:{ict_conditions_met}개) → 홀드")
        elif result['confluence'] >= effective_min:
            result['action'] = side
            result['reasons'].append(f"✅ [자율진입] 컨플루언스 {result['confluence']:.1f}/{self.max_score:.1f} ADX={adx_val:.0f} → {side.upper()}")
        else:
            result['action'] = 'hold'
            result['reasons'].append(f"⏸ [점수 미달] 조건 미달: {result['confluence']:.1f}/{self.max_score:.1f} (최소 {effective_min:.1f})")
            
        return result

    def record_trade(self, current_time=None):
        """일반 거래 실행 후 쿨다운 타이머를 시작합니다."""
        import time as _time
        if current_time:
            self.last_trade_time = current_time.timestamp() if hasattr(current_time, 'timestamp') else float(current_time)
        else:
            self.last_trade_time = _time.time()

    def record_scalp_trade(self, current_time=None):
        """스캘프 거래 실행 후 스캘프 전용 쿨다운 타이머를 시작합니다. (메인 쿨다운과 독립)"""
        import time as _time
        if current_time:
            self.last_scalp_trade_time = current_time.timestamp() if hasattr(current_time, 'timestamp') else float(current_time)
        else:
            self.last_scalp_trade_time = _time.time()

    def _analyze_ltf_scalp(self, df_ltf, bias_4h, bias_1d, current_time, now_ts):
        """
        LTF 스캘프 모드 분석 (v4.1)
        ─────────────────────────────
        호출 조건: 4H ≠ 1D 바이어스 불일치 + enable_ltf_scalp=True
        방향: 4H 기준 (1D보다 최신 신호)
        필수 조건: 15m 스윕 → MSS(강한 변위) → POI 3단 시퀀스 모두 충족
        진입 시: scalp_mode=True, risk_multiplier=0.5 플래그 반환
        """
        result = {
            'action': 'hold',
            'confluence': 0.0,
            'reasons': [f"⚡ LTF 스캘프 경로 (4H:{bias_4h} ≠ 1D:{bias_1d})"],
            'side': None,
            'scalp_mode': True,
            'risk_multiplier': 0.5,
            'god_tier': {},
            'scores': {}
        }

        # ── 스캘프 전용 쿨다운 체크 ──
        if self.last_scalp_trade_time > 0:
            elapsed = (now_ts - self.last_scalp_trade_time) / 60
            if 0 <= elapsed < self.scalp_cooldown_minutes:
                result['reasons'].append(f"⏳ 스캘프 쿨다운 중 (남은: {self.scalp_cooldown_minutes - elapsed:.0f}분)")
                return result

        # 4H 방향 기준으로 진입 방향 결정
        side = 'buy' if bias_4h == 'bullish' else 'sell'
        result['side'] = side

        if len(df_ltf) < 30:
            result['reasons'].append("⚠️ 15m 데이터 부족")
            return result

        sweep_idx = -1
        mss_idx = -1
        is_sweep_detected = False
        has_mss = False
        mss_signals = []

        # ── 조건 1: 15m 유동성 스윕 (필수) ──
        sweeps = self.ict_engine.detect_liquidity_sweeps(df_ltf)
        recent_sweeps = [s for s in sweeps if s['index'] >= len(df_ltf) - 12]
        sweep_type_needed = 'SSL_sweep' if side == 'buy' else 'BSL_sweep'
        matching_sweeps = [s for s in recent_sweeps if s['type'] == sweep_type_needed]

        if not matching_sweeps:
            result['reasons'].append(f"❌ 스캘프 무효: {'SSL' if side=='buy' else 'BSL'} 스윕 없음")
            return result

        is_sweep_detected = True
        sweep_idx = max(s['index'] for s in matching_sweeps)
        label = "SSL" if side == 'buy' else "BSL"
        result['confluence'] += 1.0
        result['reasons'].append(f"🎯 [스캘프] {label} 유동성 스윕 (+1.0)")
        result['scores']['sweep'] = 100

        # ── 조건 2: 스윕 이후 MSS + 강한 변위 (필수) ──
        mss_signals = self.ict_engine.detect_mss(df_ltf)
        mss_type_needed = 'bullish' if side == 'buy' else 'bearish'
        post_sweep_mss = [m for m in mss_signals
                          if m['type'] == mss_type_needed
                          and m['index'] > sweep_idx
                          and m['index'] >= len(df_ltf) - 12]

        if not post_sweep_mss:
            result['reasons'].append("❌ 스캘프 무효: 스윕 이후 MSS 미감지")
            return result

        disp = self.ict_engine.calculate_displacement_strength(df_ltf, post_sweep_mss)
        if not any(d['is_strong'] for d in disp):
            result['reasons'].append("❌ 스캘프 무효: MSS 변위 약함")
            return result

        has_mss = True
        mss_idx = max(m['index'] for m in post_sweep_mss)
        result['confluence'] += 1.5
        result['reasons'].append("🔄 [스캘프] MSS + 강한 변위 (+1.5)")
        result['scores']['mss'] = 100

        # ── 조건 3: MSS 이후 POI (FVG 또는 OB) 필수 ──
        fvgs = self.ict_engine.detect_fvg(df_ltf)
        current_price = df_ltf.iloc[-1]['close']
        obs = self.ict_engine.detect_order_blocks(df_ltf, mss_signals)

        has_fvg, has_ob = False, False
        if side == 'buy':
            has_fvg = any(f['bottom'] * 0.998 <= current_price <= f['top'] * 1.002
                          for f in fvgs if f['type'] == 'bullish' and f['index'] >= mss_idx - 10)
            has_ob = any(o['bottom'] * 0.998 <= current_price <= o['top'] * 1.002
                         for o in obs if o['type'] == 'bullish_OB')
        else:
            has_fvg = any(f['bottom'] * 0.998 <= current_price <= f['top'] * 1.002
                          for f in fvgs if f['type'] == 'bearish' and f['index'] >= mss_idx - 10)
            has_ob = any(o['bottom'] * 0.998 <= current_price <= o['top'] * 1.002
                         for o in obs if o['type'] == 'bearish_OB')

        if not has_fvg and not has_ob:
            result['reasons'].append("❌ 스캘프 무효: POI 없음")
            return result

        poi_score = 1.5 if (has_fvg and has_ob) else 1.0
        desc = "FVG & OB 동시" if poi_score == 1.5 else ("FVG" if has_fvg else "오더블록")
        result['confluence'] += poi_score
        result['reasons'].append(f"📦 [스캘프] 타점: {desc} (+{poi_score})")
        result['scores']['poi'] = min(100, poi_score * 100)

        # ── 최종 판별 ──
        if result['confluence'] >= self.ltf_scalp_min_confluence:
            result['action'] = side
            result['reasons'].append(
                f"⚡ [스캘프 진입] 컨플루언스 {result['confluence']:.1f}/{self.ltf_scalp_min_confluence:.1f} "
                f"(4H:{bias_4h} 방향 / 사이즈 50%) → {side.upper()}"
            )
        else:
            result['reasons'].append(
                f"⏸ [스캘프 미달] {result['confluence']:.1f}/{self.ltf_scalp_min_confluence:.1f}"
            )

        return result


if __name__ == "__main__":
    print("아이린: 두뇌(DecisionMaker) v3 (신급) 모듈 단독 테스트 준비 완료")
