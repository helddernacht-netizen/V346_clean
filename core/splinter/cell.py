
"""
SPLINTERZELLE - Kernlogik V3.4 - 3 Bedingungen + Hold Modus - ECHT
Alle Regeln aus BRAINSTORM LOG berücksichtigt
"""
import pandas as pd
from dataclasses import dataclass
from typing import Literal, Optional
from core.leonardo.reasoning import check_bedingung_1_trend_relativ, calc_atr

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
    bed1_meta: dict
    bed4_meta: dict

def calc_sl_relativ(vol_24h_pct: float, atr: float, bb_width: float = 2.0) -> tuple[float, float]:
    """
    BEDINGUNG 2 - STOP-LOSS RELATIV - Aus Log V3.4
    Erkenntnis: HYPE 7d -8.4% volatil + SL 1.2*ATR = -0.35% zu eng = 50% Loss

    NEU:
    - Wenn 24h wenig volatil (BB eng): SL 1.5*ATR eng
    - Wenn 24h volatil fallend (wie HYPE -8%): SL 2.2-2.5*ATR breit
    - BE nach +1.5% Gewinn sofort auf Entry
    - Prinzip: Lieber einmal -0.7% halten als 2x -0.35% ausgestoppt
    """
    vol_abs = abs(vol_24h_pct)
    # Volatilität aus 24h Change + BB Width
    if vol_abs < 1.5 and bb_width < 1.8:
        mult = 1.5
    elif vol_abs < 3.0:
        mult = 2.2
    else:
        mult = 2.5  # HYPE Fall: -8% => 2.5x breit
    
    sl_distance = atr * mult
    return sl_distance, mult

def calc_hold_modus(bed1_meta: dict, vol_24h: float = 0) -> tuple[HoldMode, int, float, float]:
    """
    BEDINGUNG 3 - TREASURE HOLD RELATIV - Aus Log
    Vor Entry schon Hold-Modus definieren basierend auf Bedingung 1 Historie

    Kurz-Hold: 24h stark zappelt -> +1-2% Ziel, 2-4h max
    Mittel-Hold: 30d seitwärts gesund -> 12-24h, Loss halten nicht sofort SL
    Lang-Hold: 180d Korrektur sweet -> 3-7 Tage

    Twist: Wenn -0.7% im Minus und Mittel/Lang geplant -> NICHT raus, Hold verlängern
    """
    t24 = bed1_meta.get("t24","down")
    t30 = bed1_meta.get("t30","sideways_zappelnd")
    change_30d = bed1_meta.get("change_30d",0)
    ath_dd = bed1_meta.get("ath_dd", -15)

    # KURZ: 24h stark zappelnd = Volatilität hoch
    if t24 == "sideways_zappelnd" and abs(vol_24h) > 5:
        return "KURZ", 4, 2.0, -1.0
    
    # LANG: 180d Korrektur sweet -10 bis -30 + 30d seitwärts = echter Treasure Rebound
    if -30 <= ath_dd <= -10 and -5 <= change_30d <= 5:
        return "LANG", 168, 8.0, -1.5  # 7 Tage
    
    # MITTEL: Default gesunder seitwärts Dip = 30d +3.5% seitwärts Beispiel HYPE
    return "MITTEL", 24, 4.0, -1.2

class SplinterCell:
    def __init__(self):
        self.inspected_count = 0

    def inspect(self, symbol: str, ohlc_24h, ohlc_30d, ohlc_180d, vol_24h_pct: float, atr: float, bb_width: float, moneyflow_ok: bool, moneyflow_meta: dict) -> SplinterDecision:
        # Bed1 - Trend Relativ - Die Splitterbesichtigung
        passed_b1, bed1_meta = check_bedingung_1_trend_relativ(ohlc_24h, ohlc_30d, ohlc_180d)
        
        # Bed4 kommt von außen (MoneyFlow)
        passed_b4 = moneyflow_ok

        # Bed2 SL relativ
        sl_dist, mult = calc_sl_relativ(vol_24h_pct, atr, bb_width)

        # Bed3 Hold
        hold_mode, max_hours, target_pct, max_dd = calc_hold_modus(bed1_meta, vol_24h_pct)

        # Nur wenn beide Bedingungen passen = Double Confirmation (Log Regel)
        # Splinter sagt nur JA wenn: Preis fällt (Bed1) UND Geld fließt raus (Bed4)
        ready = passed_b1 and passed_b4

        meta_combined = {**bed1_meta, "moneyflow": moneyflow_meta, "sl_dist": sl_dist, "vol_24h": vol_24h_pct}

        return SplinterDecision(
            symbol=symbol,
            passed_bed1=passed_b1,
            passed_bed4=passed_b4,
            hold_mode=hold_mode,
            sl_multiplier=mult,
            max_hold_hours=max_hours,
            target_pct=target_pct,
            max_drawdown_pct=max_dd,
            meta=meta_combined,
            ready_for_entry=ready,
            bed1_meta=bed1_meta,
            bed4_meta=moneyflow_meta
        )
