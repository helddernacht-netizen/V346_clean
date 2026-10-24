
"""
TURTLE SCANNER - Modul A - 100 Coins Pool - ECHT 5 BÖRSEN
Kein Mock mehr
"""
import time
from typing import List
from core.leonardo.reasoning import get_market_data, calc_bollinger_width, calc_rsi, calc_volatility_spike

class TurtleScanner:
    def __init__(self, universe_100: list):
        self.universe = universe_100
        self.vorauswahl_queue = []  # max 20 - Regel aus Log: Kein fester Score 9/10 = sofort Trade, sondern Queue

    def scan_once(self, get_market_data_fn=None) -> List[dict]:
        """
        Echte Suche über 5 Börsen via get_market_data (Binance, Coinbase, Bybit, OKX, Kraken)
        """
        from core.leonardo.reasoning import get_market_data as real_get
        if get_market_data_fn is None:
            get_market_data_fn = real_get

        new_entries = []
        for coin in self.universe:
            try:
                data = get_market_data_fn(coin)
                price = data.get("price",0)
                if price == 0:
                    continue
                ohlc = data.get("ohlc_1h")
                if ohlc is None or len(ohlc)<20:
                    continue

                bb = calc_bollinger_width(ohlc)
                rsi = calc_rsi(ohlc['close'])
                # vol ratio
                try:
                    avg_vol = ohlc['volume'].rolling(20).mean().iloc[-1]
                    curr_vol = ohlc['volume'].iloc[-1]
                    vol_ratio = curr_vol/avg_vol if avg_vol>0 else 1.0
                except:
                    vol_ratio = 1.0

                change = data.get("price_change_24h",0)
                spike_score = calc_volatility_spike(bb, rsi, vol_ratio, change)

                # Regel: Nur Score >=6 kommt in Vorauswahl, max 20
                if spike_score >= 6:
                    new_entries.append({
                        "symbol": coin,
                        "score": spike_score,
                        "price": price,
                        "change": change,
                        "bb_width": bb,
                        "rsi": rsi,
                        "vol_ratio": vol_ratio,
                        "source": data.get("source",""),
                        "ts": time.time()
                    })
            except Exception as e:
                # print(f"Turtle {coin} fail {e}")
                continue
            # Rate limit - wichtig für 5 Börsen
            time.sleep(0.2)

        # Sort by score desc, keep max 20
        new_entries = sorted(new_entries, key=lambda x: x["score"], reverse=True)
        # Merge mit alter Queue, deduplizieren, neueste oben
        existing_syms = {e["symbol"]: e for e in self.vorauswahl_queue}
        for e in new_entries:
            existing_syms[e["symbol"]] = e
        
        merged = sorted(existing_syms.values(), key=lambda x: (x["score"], x["ts"]), reverse=True)[:20]
        self.vorauswahl_queue = merged
        return merged

    def get_top_for_splinter(self, n=8) -> List[dict]:
        return self.vorauswahl_queue[:n]
