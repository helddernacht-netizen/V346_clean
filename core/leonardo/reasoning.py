STABLECOIN_BLACKLIST=['USDT','USDC','DAI']
def get_market_data(s): return {'symbol':s,'price':0}
def check_filters(s,d,o): return True,{}, {}
def get_ohlc_three_windows(s): return None,None,None
def calc_atr(o): return 0.01
def calc_bollinger_width(o): return 0.3
def calc_rsi(c): return 50
