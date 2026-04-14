class RiskManager:
    def __init__(self, risk_per_trade=0.02):
        self.risk_per_trade = risk_per_trade

    def calculate_position_size(self, balance, entry_price, stop_loss_price):
        """
        리스크 비율과 진입/손절가를 기반으로 포지션 사이즈(수량)를 계산합니다.
        - balance: 현재 가용 잔고 (USDT)
        - entry_price: 진입 가격
        - stop_loss_price: 무효화 지점 (손절 가격)
        """
        if entry_price == stop_loss_price:
            return 0
            
        # 1회 거래당 감수할 달러 리스크
        risk_amount = balance * self.risk_per_trade
        
        # 가격 하락/상승 폭 (%)
        price_diff_percent = abs(entry_price - stop_loss_price) / entry_price
        
        # 포지션 수량 (Quantity)
        # Position Size (Qty) = Risk Amount / (Price Diff)
        if price_diff_percent == 0:
            return 0
            
        position_qty = risk_amount / abs(entry_price - stop_loss_price)
        
        # 필요 레버리지 역산
        # Leverage = (Position Size * Price) / Balance
        required_leverage = (position_qty * entry_price) / balance
        
        return {
            'risk_amount': risk_amount,
            'position_qty': position_qty,
            'required_leverage': required_leverage,
            'stop_loss_pct': price_diff_percent * 100
        }

    def validate_setup(self, risk_reward_ratio, min_rr=1.5):
        """
        손익비(R:R)가 최소 기준을 충족하는지 검증합니다.
        """
        if risk_reward_ratio >= min_rr:
            return True, f"아이린: 손익비 {risk_reward_ratio:.2f}로 진입 조건에 부합합니다. 추격 준비를 마쳤습니다."
        else:
            return False, f"아이린: 손익비 {risk_reward_ratio:.2f}가 너무 낮습니다. 가성비 떨어지는 자리는 들어가지 않습니다."

if __name__ == "__main__":
    rm = RiskManager(risk_per_trade=0.02)
    # 예시: 잔고 1000불, 65000불 롱 진입, 64200불 손절
    balance = 1000
    entry = 65000
    sl = 64200
    
    result = rm.calculate_position_size(balance, entry, sl)
    print("아이린 리스크 관리 리포트:")
    for key, val in result.items():
        print(f"- {key}: {val:.4f}")
