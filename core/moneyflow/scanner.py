
"""
MONEY FLOW SCANNER - Bedingung 4 - Zweiter Scanner parallel - ECHT 5 BÖRSEN
Kein Mock, echte Daten von Binance, Coinbase, Bybit, OKX, Kraken

Regeln aus Brainstorm Log V3.4:
- Zweiter Scanner läuft parallel alle 15 Min
- Cross-Exchange Volumen: Binance Spot Vol + Bybit + Coinbase + OKX + Kraken
  Wenn HYPE -8% und alle 3 Börsen Vol -20% = Kein frisches Geld = Fall geht weiter = GUT
  Wenn HYPE -8% aber Binance Vol +40% = Geld fließt rein = Vorsicht, könnte springen
- Funding + OI: Funding negativ = Viele shorten schon = Short Squeeze Gefahr = VORSICHT
  OI fällt + Preis fällt = Echter Abverkauf = GUT
- Stablecoin Flows: USDT Dominanz steigt = Geld geht aus Alts raus = fallende Coins Setup perfekt
"""

import time
import requests
from dataclasses import dataclass
from typing import Optional, Dict
import pandas as pd

@dataclass
class MoneyFlowSignal:
    symbol: str
    exchange_vol_change: float  # % vs Vortag gemittelt über 5 Börsen
    usdt_dominance_change: float
    funding_rate: float
    open_interest: Optional[float]
    verdict: str  # "GUT", "VORSICHT", "NEUTRAL"
    ok_for_short: bool
    meta: dict

class MoneyFlowScanner:
    def __init__(self):
        self.last_scan = None
        self.usdt_dom_cache = {"value": 5.5, "change": 0.0, "ts": 0}
        self._connector = None

    def _get_connector(self):
        if self._connector is None:
            from core.exchanges.connector import connector
            self._connector = connector
        return self._connector

    def fetch_usdt_dominance(self) -> tuple[float, float]:
        """USDT Dominance von CoinGecko global - Risk-Off Indikator"""
        # Cache 15 Min
        if time.time() - self.usdt_dom_cache["ts"] < 900:
            return self.usdt_dom_cache["value"], self.usdt_dom_cache["change"]
        try:
            r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
            j = r.json()
            data = j.get("data",{})
            # USDT dominance nicht direkt, aber stablecoin mcap vs total
            # Wir nehmen usdt mcap / total mcap *100 als Proxy
            # Oder einfacher: wenn total mcap fällt + btc dom steigt = risk off
            # Für V3.4: hole stablecoin dominance via /global/decentralized_finance_defi
            # Fallback: nutze btc dominance change als risk proxy
            btc_dom = float(data.get("market_cap_percentage",{}).get("btc", 50))
            # Simpler Proxy: wenn BTC dom steigt, ist risk-off = gut für Shorts
            # Wir berechnen change vs cache
            prev = self.usdt_dom_cache["value"]
            change = btc_dom - prev if prev else 0
            self.usdt_dom_cache = {"value": btc_dom, "change": change, "ts": time.time()}
            return btc_dom, change
        except Exception as e:
            # print(f"USDT Dom fetch fail {e}")
            return self.usdt_dom_cache["value"], self.usdt_dom_cache["change"]

    def calc_cross_exchange_vol_change(self, symbol: str) -> tuple[float, Dict]:
        """
        Cross-Exchange Volumen Change: Vergleich Vol heute vs gestern über alle 5 Börsen
        GUT wenn: alle Börsen Vol -20% = kein frisches Geld
        VORSICHT wenn: Binance Vol +40% = Geld fließt rein
        """
        conn = self._get_connector()
        ohlc_map = conn.fetch_ohlcv_multi(symbol, timeframe='1d', limit=3)
        
        if not ohlc_map:
            return 0.0, {}

        changes = []
        details = {}
        for eid, df in ohlc_map.items():
            if len(df) < 2:
                continue
            try:
                vol_today = float(df['volume'].iloc[-1])
                vol_yest = float(df['volume'].iloc[-2])
                if vol_yest > 0:
                    ch = (vol_today - vol_yest)/vol_yest*100
                    changes.append(ch)
                    details[eid] = ch
            except:
                continue
        
        avg_change = sum(changes)/len(changes) if changes else 0.0
        return avg_change, details

    def scan(self, symbol: str, price_change_24h: float) -> MoneyFlowSignal:
        conn = self._get_connector()
        
        # 1. Cross-Exchange Vol Change
        vol_change_avg, vol_details = self.calc_cross_exchange_vol_change(symbol)
        
        # 2. Funding Rate
        funding = conn.fetch_funding_rate(symbol)
        funding_val = float(funding) if funding is not None else 0.0

        # 3. Open Interest
        oi = conn.fetch_open_interest(symbol)

        # 4. USDT Dominance / BTC Dom als Risk-Off Proxy
        usdt_dom, usdt_dom_change = self.fetch_usdt_dominance()

        # === LOGIK nach Brainstorm Log ===
        # Beispiel HYPE: Bei uns -8.4% und 9/10 Score = sieht gut aus
        # Aber was wenn auf Binance + Coinbase gleichzeitig +5% Vol reinfließt?
        # Dann ist unser -8.4% nur lokaler Zappel und wir werden ausgestoppt.
        # Wenn aber überall -8% und Vol bricht ein, dann echter Fall = unser Setup.

        verdict = "NEUTRAL"
        ok_for_short = False

        # Hauptlogik: Preis fällt UND Geld fließt raus = Double Confirmation
        if price_change_24h < -3:
            # Vol bricht ein = kein frisches Geld = Fall geht weiter = GUT
            if vol_change_avg < -10:
                verdict = "GUT"
                ok_for_short = True
            # Vol steigt stark = Geld fließt rein = Vorsicht Squeeze
            elif vol_change_avg > 20:
                verdict = "VORSICHT"
                ok_for_short = False
            else:
                # neutraler Vol, schau auf Funding und USDT Dom
                if funding_val < -0.02:  # stark negativ = viele Shorts schon = Squeeze Gefahr
                    verdict = "VORSICHT"
                    ok_for_short = False
                elif usdt_dom_change > 0.3:  # BTC Dom steigt = Risk-Off = gut für fallende Coins
                    verdict = "GUT"
                    ok_for_short = True
                else:
                    verdict = "NEUTRAL"
                    ok_for_short = usdt_dom_change > 0 or funding_val >= 0
        else:
            # Preis fällt nicht genug = kein Setup
            verdict = "NEUTRAL"
            ok_for_short = False

        # USDT Dom Booster Regel aus Log:
        # USDT Dominanz steigt = Geld geht aus Alts raus = Unser fallende Coins Setup perfekt
        # USDT Dominanz fällt = Geld geht in Alts rein = Lieber nicht shorten
        if usdt_dom_change > 0.5 and price_change_24h < -2:
            ok_for_short = True
            verdict = "GUT"

        # Funding Regel:
        # Funding Rate negativ = Viele shorten schon = Short Squeeze Gefahr = VORSICHT
        if funding_val < -0.05:
            ok_for_short = False
            verdict = "VORSICHT"

        # OI Regel:
        # OI fällt + Preis fällt = Echter Abverkauf = GUT
        # (OI Daten brauchen Historie, hier nur als Meta)

        meta = {
            "binance_vol": vol_details.get("binance",0),
            "coinbase_vol": vol_details.get("coinbase",0),
            "bybit_vol": vol_details.get("bybit",0),
            "okx_vol": vol_details.get("okx",0),
            "kraken_vol": vol_details.get("kraken",0),
            "avg_vol_change": vol_change_avg,
            "vol_details": vol_details,
            "usdt_dom": usdt_dom,
            "usdt_dom_change": usdt_dom_change,
            "funding": funding_val,
            "open_interest": oi,
            "price_change": price_change_24h
        }

        return MoneyFlowSignal(
            symbol=symbol,
            exchange_vol_change=vol_change_avg,
            usdt_dominance_change=usdt_dom_change,
            funding_rate=funding_val,
            open_interest=oi,
            verdict=verdict,
            ok_for_short=ok_for_short,
            meta=meta
        )
