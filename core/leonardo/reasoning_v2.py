"""
V3.4 LEONARDO - REASONING - ECHTE BÖRSENDATEN, KEIN MOCK
Alle Regeln aus BRAINSTORM LOG V3.4 berücksichtigt
"""
import pandas as pd
import numpy as np
from typing import Tuple, Dict, Optional
import time

STABLECOIN_BLACKLIST = ["USDT","USDC","DAI","BUSD","TUSD","FDUSD","USDP","GUSD","EUR","USD","EURT"]

def get_connector():
    from core.exchanges.connector import connector
    return connector

def calc_rsi(series: pd.Series, period: int = 14) -> float:
    try:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])
    except:
        return 50.0

def calc_bollinger_width(df: pd.DataFrame, period: int = 20) -> float:
    try:
        sma = df['close'].rolling(period).mean()
        std = df['close'].rolling(period).std()
        upper = sma + 2*std
        lower = sma - 2*std
        width = (upper - lower) / sma * 100
        return float(width.iloc[-1])
    except:
        return 2.5

def calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    try:
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr)
    except:
        return float(df['close'].iloc[-1]*0.015 if len(df)>0 else 0.01)

def calc_volatility_spike(bb_width: float, rsi_1h: float, vol_ratio: float, change_24h: float) -> float:
    score = 0
    if bb_width < 1.8: score += 3
    elif bb_width < 2.5: score += 1
    if 25 < rsi_1h < 65: score += 2
    if vol_ratio > 1.6: score += 3
    elif vol_ratio > 1.2: score += 1
    if change_24h < -3: score += 2
    elif change_24h < 0: score += 1
    return score

def calc_trend_direction(ohlc_df: Optional[pd.DataFrame]) -> str:
    if ohlc_df is None or len(ohlc_df) < 20:
        return "unknown"
    try:
        sma20 = ohlc_df['close'].rolling(20).mean().iloc[-1]
        sma50 = ohlc_df['close'].rolling(50).mean().iloc[-1] if len(ohlc_df)>=50 else sma20
        price = ohlc_df['close'].iloc[-1]
        price_ago = ohlc_df['close'].iloc[-10] if len(ohlc_df)>=10 else ohlc_df['close'].iloc[0]
        change = (price - price_ago)/price_ago*100 if price_ago!=0 else 0
        if change > 3 and price > sma20 and sma20 > sma50:
            return "up"
        elif -5 <= change <= 5:
            return "sideways_zappelnd"
        else:
            return "down"
    except:
        return "unknown"

def check_bedingung_1_trend_relativ(
    data_24h: Optional[pd.DataFrame],
    data_30d: Optional[pd.DataFrame],
    data_180d: Optional[pd.DataFrame]
) -> Tuple[bool, dict]:
    t24 = calc_trend_direction(data_24h)
    t30 = calc_trend_direction(data_30d)
    t180 = calc_trend_direction(data_180d)

    ath_drawdown = -15.0
    change_30d_pct = 0.0
    if data_180d is not None and len(data_180d)>0:
        try:
            ath = data_180d['high'].max()
            curr = data_180d['close'].iloc[-1]
            ath_drawdown = (curr-ath)/ath*100 if ath!=0 else -15
        except:
            ath_drawdown = -15

    if data_30d is not None and len(data_30d)>=2:
        try:
            first = data_30d['close'].iloc[0]
            last = data_30d['close'].iloc[-1]
            change_30d_pct = (last-first)/first*100 if first!=0 else 0
        except:
            change_30d_pct = 0

    reasons = []
    ok = True
    fail_codes = []

    if t24 == "up":
        ok = False
        fail_codes.append("24h_up")
        reasons.append("24h aufwärts = Foot der schon rennt -> RAUS")
    elif t24 == "unknown":
        reasons.append("24h unknown -> neutral")
    else:
        reasons.append(f"24h {t24} OK - fällt leicht / zappelt")

    if change_30d_pct > 20:
        ok = False
        fail_codes.append("30d_hot")
        reasons.append(f"30d +{change_30d_pct:.1f}% zu heiß >+20% -> RAUS")
    elif change_30d_pct < -10:
        ok = False
        fail_codes.append("30d_tot")
        reasons.append(f"30d {change_30d_pct:.1f}% tot <-10% -> RAUS")
    else:
        if -5 <= change_30d_pct <= 5:
            reasons.append(f"30d {change_30d_pct:.1f}% Zappel gesund Sweet Spot")
        else:
            reasons.append(f"30d {change_30d_pct:.1f}% moderat OK")

    if t30 == "up" and t24 == "up":
        ok = False
        fail_codes.append("30d_up_trend")
        reasons.append("30d nur Aufwärts + 24h aufwärts = RAUS")

    if ath_drawdown > -5:
        ok = False
        fail_codes.append("180d_no_dip")
        reasons.append(f"180d ATH {ath_drawdown:.1f}% >-10% nie gefallen -> RAUS")
    elif ath_drawdown < -50:
        ok = False
        fail_codes.append("180d_dead")
        reasons.append(f"180d ATH {ath_drawdown:.1f}% <-50% Totcoin -> RAUS")
    else:
        if -30 <= ath_drawdown <= -10:
            reasons.append(f"180d ATH {ath_drawdown:.1f}% SWEET -10 bis -30%")
        else:
            reasons.append(f"180d ATH {ath_drawdown:.1f}% im Korridor OK")

    meta = {
        "t24": t24, "t30": t30, "t180": t180,
        "ath_dd": ath_drawdown,
        "change_30d": change_30d_pct,
        "reasons": reasons,
        "fail_codes": fail_codes
    }
    return ok, meta

def get_market_data(symbol: str) -> dict:
    connector = get_connector()
    tickers = connector.fetch_ticker_safe(symbol)
    
    if not tickers:
        return {
            "price": 0.0,
            "price_change_24h": 0.0,
            "vol24h": 0.0,
            "source": "none",
            "tickers": {},
            "ohlc_1h": None
        }

    primary = tickers.get('binance') or tickers.get('bybit') or tickers.get('okx') or list(tickers.values())[0]
    price = float(primary.get('last') or primary.get('close') or 0)
    change_24h = float(primary.get('percentage') or 0)
    vol24h = 0
    for t in tickers.values():
        vol24h += float(t.get('quoteVolume') or t.get('baseVolume') or 0)

    ohlc_1h = connector.fetch_ohlcv_safe(symbol, timeframe='1h', limit=100)
    if ohlc_1h is None:
        ohlc_1h = connector.fetch_ohlcv_safe(symbol, timeframe='15m', limit=100)

    return {
        "price": price,
        "price_change_24h": change_24h,
        "vol24h": vol24h,
        "source": ",".join(tickers.keys()),
        "tickers": tickers,
        "ohlc_1h": ohlc_1h
    }

def check_filters(symbol: str, data: dict, open_syms: list) -> Tuple[bool, dict, dict]:
    ohlc = data.get("ohlc_1h")
    if ohlc is not None and len(ohlc)>=20:
        bb_bw = calc_bollinger_width(ohlc)
        rsi_1h = calc_rsi(ohlc['close'])
        atr = calc_atr(ohlc)
        try:
            avg_vol = ohlc['volume'].rolling(20).mean().iloc[-1]
            curr_vol = ohlc['volume'].iloc[-1]
            vol_ratio = curr_vol/avg_vol if avg_vol>0 else 1.0
        except:
            vol_ratio = 1.0
    else:
        bb_bw = 2.0
        rsi_1h = 50.0
        vol_ratio = 1.0
        atr = data.get("price",0.01)*0.015

    spike = calc_volatility_spike(bb_bw, rsi_1h, vol_ratio, data.get("price_change_24h",0))
    ok = spike >= 6 and symbol not in open_syms and data.get("price",0)>0
    
    checks = {
        "bb": {"ok": bb_bw < 1.8, "value": f"{bb_bw:.2f}%"},
        "vol": {"ok": vol_ratio > 1.6, "value": f"{vol_ratio:.2f}x"},
        "rsi": {"ok": 25 < rsi_1h < 65, "value": f"{rsi_1h:.1f}"},
        "spike_score": {"ok": spike>=6, "value": f"{spike}/10"},
        "change_24h": {"ok": data.get("price_change_24h",0) < 5, "value": f"{data.get('price_change_24h',0):+.1f}%"},
    }
    meta = {"bb_bw": bb_bw, "rsi_1h": rsi_1h, "vol_ratio": vol_ratio, "atr": atr, "sma20": 0, "price_change_24h": data.get("price_change_24h",0), "source": data.get("source")}
    return ok, checks, meta

def get_ohlc_three_windows(symbol: str):
    connector = get_connector()
    ohlc_24h = connector.fetch_ohlcv_safe(symbol, timeframe='1h', limit=24)
    ohlc_30d = connector.fetch_ohlcv_safe(symbol, timeframe='1d', limit=30)
    ohlc_180d = connector.fetch_ohlcv_safe(symbol, timeframe='1d', limit=180)
    return ohlc_24h, ohlc_30d, ohlc_180d
