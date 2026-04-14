"""
아이린 바벨(Barbell) 전략 관리자
────────────────────────────────────────────────
코어(안정)  : ICT DecisionMaker — 높은 컨플루언스, 낮은 레버리지, 자본 보존
위성(공격)  : SatelliteStrategy — 킬존 FVG 스나이핑, 고레버리지, 복리 베팅

자본 배분 (기본):
  코어  70~80%  → 안정적 복리 누적
  위성  20~30%  → 폭발적 수익 추구

두 전략은 완전히 독립된 자본 풀로 운용됩니다.
한쪽이 손실을 내도 다른 쪽 자본에 영향 없음.
"""


class BarbellManager:
    def __init__(
        self,
        core_decision_maker,        # core/decision_maker.py :: DecisionMaker
        satellite_strategy,         # strategy/satellite.py  :: SatelliteStrategy
        total_capital: float = 1556.0,
        satellite_ratio: float = 0.30,  # 위성 자본 비율 (0.20 ~ 0.30)
    ):
        self.core = core_decision_maker
        self.satellite = satellite_strategy
        self.total_capital = total_capital
        self.satellite_ratio = satellite_ratio
        self.core_ratio = 1.0 - satellite_ratio

    # ──────────────────────────────────────────
    # 통합 분석
    # ──────────────────────────────────────────
    def analyze(self, data_dict: dict, symbol: str, current_time=None) -> dict:
        """
        코어 + 위성 전략을 동시에 분석하여 반환.
        두 전략이 동시에 신호를 낼 수 있으며,
        각각 독립된 포지션으로 처리됩니다.

        Returns:
            {
                'core'     : core signal dict,
                'satellite': satellite signal dict,
            }
        """
        core_signal = self.core.analyze_entry(
            data_dict, symbol=symbol, current_time=current_time
        )
        satellite_signal = self.satellite.analyze_entry(
            data_dict, current_time=current_time
        )
        return {
            'core': core_signal,
            'satellite': satellite_signal,
        }

    # ──────────────────────────────────────────
    # 거래 결과 반영
    # ──────────────────────────────────────────
    def record_core_trade(self, current_time=None):
        """코어 거래 종료 후 쿨다운 업데이트"""
        self.core.record_trade(current_time=current_time)

    def record_satellite_result(self, pnl: float, is_win: bool, current_time=None):
        """위성 거래 종료 후 복리 배율 + 자본 업데이트"""
        if is_win:
            self.satellite.record_win(pnl, current_time=current_time)
        else:
            self.satellite.record_loss(pnl, current_time=current_time)

    # ──────────────────────────────────────────
    # 상태 리포트
    # ──────────────────────────────────────────
    def status_report(self) -> dict:
        """바벨 전략 전체 현황 요약"""
        sat = self.satellite.status_report()
        core_capital = self.total_capital * self.core_ratio  # 단순 추정 (실잔고는 executor에서)

        print("\n" + "═" * 50)
        print("⚖️  바벨 전략 현황 리포트")
        print("═" * 50)
        print(f"  🔵 코어  (안정) : 자본 ~{core_capital:.0f} USDT ({self.core_ratio*100:.0f}%)")
        print(f"  🔴 위성  (공격) : {sat['current_capital']:.2f} USDT "
              f"(ROI {sat['roi_pct']:+.2f}%)")
        print(f"     복리배율   : {sat['compound_factor']:.3f}x")
        print(f"     연속수익   : {sat['consecutive_wins']}회")
        print(f"     연속손실   : {sat['consecutive_losses']}회")
        print("═" * 50 + "\n")
        return {
            'core_capital_est': round(core_capital, 2),
            'satellite': sat,
        }
