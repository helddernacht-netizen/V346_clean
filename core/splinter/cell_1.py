"""
SPLINTERZELLE - Kernlogik V3.4 - 3 Bedingungen + Hold Modus
"""
import pandas as pd
from dataclasses import dataclass
from typing import Literal
from core.leonardo.reasoning import check_bedingung_1_trend_relativ

HoldMode = Literal["KURZ","MITTEL","LANG"]

@dataclass
class SplinterDecision:
    symbol: str
    passed_bed1: bool
    passed_bed4: bool
    hold_mode: HoldMode
    sl_multiplier: float
    max_hold_hours: int
    target_pct: float
    max_drawdown_pct: float
    meta: dict
    ready_for_entry: bool

def calc_sl_relativ(vol_24h_pct: float, atr: float) -> tuple[float, float]:
    """
    BEDINGUNG 2 - STOP LOSS RELATIV
    HYPE 7d -8.4% + SL 1.2*ATR = -0.35% zu eng -> 50% Loss
    NEU: breiter je volatiler
    """
    vol_abs = abs(vol_24h_pct)
    if vol_abs < 1.5:
        mult = 1.5
    elif vol_abs < 3.0:
        mult = 2.2
    else:
        mult = 2.5
    sl_distance = atr * mult
    return sl_distance, mult

def calc_hold_modus(bed1_meta: dict) -> tuple[HoldMode, int, float, float]:
    """
    BEDINGUNG 3 - TREASURE HOLD RELATIV
    Vor Entry Hold-Modus definieren
    """
    t24 = bed1_meta.get("t24","down")
    t30 = bed1_meta.get("t30","sideways_zappelnd")
    t180 = bed1_meta.get("t180","down")
    ath_dd = bed1_meta.get("ath_dd", -15)

    # KURZ: 24h stark zappelnd
    if t24 == "sideways_zappelnd":
        return "KURZ", 4, 2.0, -1.0  # 4h max, +2% Ziel, -1% MaxDD
    
    # LANG: 180d Korrektur sweet -10 bis -30
    if -30 <= ath_dd <= -10 and t30 == "sideways_zappelnd":
        return "LANG", 168, 8.0, -1.5  # 7 Tage, +8%, -1.5%
    
    # MITTEL: Default gesunder seitwärts
    return "MITTEL", 24, 4.0, -1.2

class SplinterCell:
    def __init__(self):
        self.inspected_count = 0

    def inspect(self, symbol: str, ohlc_24h, ohlc_30d, ohlc_180d, vol_24h_pct: float, atr: float, moneyflow_ok: bool, moneyflow_meta: dict) -> SplinterDecision:
        # Bed1
        passed_b1, bed1_meta = check_bedingung_1_trend_relativ(ohlc_24h, ohlc_30d, ohlc_180d)
        
        # Bed4 kommt von außen
        passed_b4 = moneyflow_ok

        # Bed2 SL
        sl_dist, mult = calc_sl_relativ(vol_24h_pct, atr)

        # Bed3 Hold
        hold_mode, max_hours, target_pct, max_dd = calc_hold_modus(bed1_meta)

        ready = passed_b1 and passed_b4

        return SplinterDecision(
            symbol=symbol,
            passed_bed1=passed_b1,
            passed_bed4=passed_b4,
            hold_mode=hold_mode,
            sl_multiplier=mult,
            max_hold_hours=max_hours,
            target_pct=target_pct,
            max_drawdown_pct=max_dd,
            meta={**bed1_meta, "moneyflow": moneyflow_meta, "sl_dist": sl_dist},
            ready_for_entry=ready
        )
