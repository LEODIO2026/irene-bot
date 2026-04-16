import sys
import os
import pandas as pd
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.decision_maker import DecisionMaker
from core.ict_engine import ICTEngine

def run_test():
    ict_engine = ICTEngine()
    dm = DecisionMaker(ict_engine, min_confluence=5.0)

    # Mock Data
    now = pd.Timestamp.now()
    df_htf = pd.DataFrame({'close': [100]*30, 'high': [102]*30, 'low': [98]*30})
    df_htf['ema50'] = 90
    df_htf['ema20'] = 95 # Bullish HTF
    
    # Missing sweep and MSS
    df_ltf = pd.DataFrame({'close': [100]*30, 'high': [102]*30, 'low': [98]*30, 'timestamp': [now]*30})

    data_dict = {
        '4h': df_htf,
        '1d': df_htf,
        '15m': df_ltf,
        'mock_external': {
            'smart_money': {'score': 2.0, 'reasons': ['Smart Money Long']},
            'crowd': {'score': 1.0, 'reasons': ['Crowd Fear']},
            'whale': {'score': 1.0, 'reasons': ['Whale Accumulation']},
            'news': {'score': 0.5, 'reasons': ['Bullish News']}
        }
    }

    res = dm.analyze_entry(data_dict, current_time=now)
    print("Test Result:")
    print(res['action'])
    print(res['reasons'])

if __name__ == '__main__':
    run_test()
