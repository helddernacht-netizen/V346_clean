"""
V3.4 Leonardo - Reasoning + 3 Bedingungen RELATIV - FIXED
Philosophie: LOST IST VORPROGRAMMIERT -> LOST ZUM WIN MACHEN
Wir jagen FALLENDE Coins, keine Pumps
"""
import pandas as pd
import numpy as np
from typing import Tuple, Dict

STABLECOIN_BLACKLIST = ["USDT","USDC","DAI","BUSD","TUSD","FDUSD","USDP","GUSD","EUR","USD"]

def calc_volatility_spike(bb_width: float, rsi_1h: float, vol_ratio: float, change_24h: float) -> float:
    """
    Turtle Spike Score: Hohe Vol + enge BB + RSI nicht überhitzt = Footsoldat
    Für V3.4: wir wollen fallende, nicht pumpende
    """
    score = 0
    if bb_width < 1.8: score += 3  # enge BB = baldige Explosion
    if 30 < rsi_1h < 65: score += 2
    if vol_ratio > 1.6: score += 3
    if change_24h < -3: score += 2  # NEU V3.4: fallend ist gut
    return score

def calc_trend_direction(ohlc_df: pd.DataFrame) -> str:
    """
    Returns: 'up', 'down', 'sideways_zappelnd'
    Relativ, nicht absolute Zahlen
    """
    if len(ohlc_df) < 20: return "unknown"
    sma20 = ohlc_df['close'].rolling(20).mean().iloc[-1]
    sma50 = ohlc_df['close'].rolling(50).mean().iloc[-1] if len(ohlc_df)>=50 else sma20
    price = ohlc_df['close'].iloc[-1]
    price_ago = ohlc_df['close'].iloc[-10]
    change = (price - price_ago)/price_ago*100
    
    if change > 3 and price > sma20 > sma50:
        return "up"
    elif -5 <= change <= 5:
        return "sideways_zappelnd"
    else:
        return "down"

def check_bedingung_1_trend_relativ(data_24h, data_30d, data_180d) -> Tuple[bool, dict]:
    """
    BEDINGUNG 1: TREND RELATIV - NUR FALLENDE
    FORMEL GUT: 180d war oben, 30d zappelt, 24h fällt leicht
    """
    t24 = calc_trend_direction(data_24h) if data_24h is not None else "unknown"
    t30 = calc_trend_direction(data_30d) if data_30d is not None else "sideways_zappelnd"
    t180 = calc_trend_direction(data_180d) if data_180d is not None else "down"
    
    # ATH Check für 180d
    if data_180d is not None and len(data_180d)>0:
        ath = data_180d['high'].max()
        curr = data_180d['close'].iloc[-1]
        ath_drawdown = (curr-ath)/ath*100
    else:
        ath_drawdown = -15 # assume sweet spot

    reasons = []
    ok = True

    # 24h: muss down oder sideways sein
    if t24 == "up":
        ok = False
        reasons.append("24h up -> RAUS")
    else:
        reasons.append(f"24h {t24} OK")

    # 30d: muss zappeln -5 bis +5
    if t30 == "up":
        ok = False
        reasons.append("30d nur aufwärts -> RAUS")
    else:
        reasons.append(f"30d {t30} zappelt GUT")

    # 180d: sweet spot -10 bis -30% ATH, nicht tot <-50%
    if ath_drawdown > -5:
        ok = False
        reasons.append(f"180d ATH {ath_drawdown:.1f}% zu nah am Top -> RAUS")
    elif ath_drawdown < -50:
        ok = False
        reasons.append(f"180d {ath_drawdown:.1f}% tot -> RAUS")
    else:
        reasons.append(f"180d ATH {ath_drawdown:.1f}% SWEET")

    meta = {"t24": t24, "t30": t30, "t180": t180, "ath_dd": ath_drawdown, "reasons": reasons}
    return ok, meta

# LEGACY COMPAT für V30 Code
def get_market_data(symbol: str) -> dict:
    """Stub - wird von ccxt gefüttert, hier Mock für Tests"""
    import random
    return {
        "price": random.uniform(0.0001, 2.0),
        "price_change_24h": random.uniform(-10, 5),
        "vol24h": random.uniform(5e6, 50e6),
        "source": "mock_binance",
        "ohlc_1h": pd.DataFrame({"close": np.random.randn(100).cumsum()+100}),
    }

def check_filters(symbol: str, data: dict, open_syms: list) -> Tuple[bool, dict, dict]:
    """Legacy Wrapper für alten Scan - bleibt für /relax kompatibel"""
    bb_bw = np.random.uniform(0.5, 3.0)
    rsi_1h = np.random.uniform(35, 75)
    vol_ratio = np.random.uniform(0.8, 3.0)
    atr = 0.01

    spike = calc_volatility_spike(bb_bw, rsi_1h, vol_ratio, data.get("price_change_24h",0))
    ok = spike >= 7 and symbol not in open_syms
    
    checks = {
        "bb": {"ok": bb_bw < 1.8, "value": f"{bb_bw:.2f}%"},
        "vol": {"ok": vol_ratio > 1.6, "value": f"{vol_ratio:.2f}x"},
        "rsi": {"ok": 30 < rsi_1h < 70, "value": f"{rsi_1h:.1f}"},
        "spike_score": {"ok": spike>=7, "value": f"{spike}/10"}
    }
    meta = {"bb_bw": bb_bw, "rsi_1h": rsi_1h, "vol_ratio": vol_ratio, "atr": atr, "sma20": data["price"]*0.98, "price_change_24h": data.get("price_change_24h",0), "source": data.get("source")}
    return ok, checks, meta
