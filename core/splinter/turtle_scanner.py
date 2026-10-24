"""
TURTLE SCANNER - Modul A - 100 Coins Pool
Scannt alle 30 Sek nach Spikes -> Vorauswahl Queue max 20
"""
import random
import time
from core.leonardo.reasoning import calc_volatility_spike

class TurtleScanner:
    def __init__(self, universe_100: list):
        self.universe = universe_100
        self.vorauswahl_queue = []  # max 20

    def scan_once(self, get_market_data_fn):
        new_queue = self.vorauswahl_queue.copy()
        for coin in self.universe:
            try:
                data = get_market_data_fn(coin)
                bb = random.uniform(0.3, 3.5)
                rsi = random.uniform(20, 80)
                vol_ratio = random.uniform(0.5, 4.0)
                change = data.get("price_change_24h",0)
                spike_score = calc_volatility_spike(bb, rsi, vol_ratio, change)
                if spike_score > 6:
                    if coin not in new_queue:
                        new_queue.append({"symbol": coin, "score": spike_score, "price": data["price"], "change": change, "ts": time.time()})
            except: continue
        
        # Sort by score, keep max 20 newest
        new_queue = sorted(new_queue, key=lambda x: x["score"], reverse=True)[:20]
        self.vorauswahl_queue = new_queue
        return new_queue

    def get_top_for_splinter(self, n=8):
        return self.vorauswahl_queue[:n]
