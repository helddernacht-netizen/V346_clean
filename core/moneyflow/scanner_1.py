"""
MONEY FLOW SCANNER - Bedingung 4 - Zweiter Scanner parallel
Input: Binance Spot Vol + Bybit + Coinbase Vol + Funding + OI + USDT Dom
Logik V3.4:
 - Coin -8% und Börsen Vol -20% = Kein Geld = Fall geht weiter = GUT
 - Coin -8% aber Binance Vol +40% = Geld rein = Squeeze Gefahr = VORSICHT
 - USDT Dom steigt = Risk-Off = Perfekt für Short
"""
import random
from dataclasses import dataclass

@dataclass
class MoneyFlowSignal:
    symbol: str
    exchange_vol_change: float  # % vs 24h avg
    usdt_dominance_change: float
    funding_rate: float
    verdict: str  # "GUT", "VORSICHT", "NEUTRAL"
    ok_for_short: bool
    meta: dict

class MoneyFlowScanner:
    def __init__(self):
        self.last_scan = None

    def scan(self, symbol: str, price_change_24h: float) -> MoneyFlowSignal:
        # TODO: Echte APIs: Binance ticker 24h, Bybit, Coinbase, Coingecko USDT Dominance
        # Mock für V3.4 Gerüst
        binance_vol_change = random.uniform(-30, 50)
        coinbase_vol_change = random.uniform(-25, 40)
        usdt_dom_change = random.uniform(-1.5, 2.0)
        funding = random.uniform(-0.05, 0.05)

        # Logik
        avg_vol_change = (binance_vol_change + coinbase_vol_change)/2

        if price_change_24h < -5:
            if avg_vol_change < -10:
                verdict = "GUT"
                ok = True  # kein Geld, Fall geht weiter
            elif avg_vol_change > 20:
                verdict = "VORSICHT"
                ok = False # Geld fließt rein -> Squeeze
            else:
                verdict = "NEUTRAL"
                ok = usdt_dom_change > 0.3 # USDT Dom steigt hilft
        else:
            verdict = "NEUTRAL"
            ok = False

        # USDT Dom Booster
        if usdt_dom_change > 0.5:
            ok = ok or price_change_24h < -3

        return MoneyFlowSignal(
            symbol=symbol,
            exchange_vol_change=avg_vol_change,
            usdt_dominance_change=usdt_dom_change,
            funding_rate=funding,
            verdict=verdict,
            ok_for_short=ok,
            meta={
                "binance_vol": binance_vol_change,
                "coinbase_vol": coinbase_vol_change,
                "usdt_dom": usdt_dom_change,
                "funding": funding,
                "price_change": price_change_24h
            }
        )
