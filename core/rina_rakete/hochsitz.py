"""
HOCHSITZ - Der feste Anker im Wald
Wie im Hirschgarten: Der Hochsitz ist das Zuhause, 100 Wallet, letztes sauberes High, letzte grüne Kerze mit Volumen.
Kein harter Zwang, nur innerer Sog.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
import numpy as np

log = logging.getLogger("RINA_HOCHSITZ")

class HochsitzAnchor:
    def __init__(self):
        self.anchors: Dict[str, Dict[str, Any]] = {}  # symbol -> {price, type, timestamp, volume}
        self.portfolio_high: float = 0.0
        log.info("[HOCHSITZ] Anker initialisiert - Hochsitz steht")

    def update_portfolio_high(self, equity: float):
        """Letztes sauberes Portfolio High - 100 Wallet"""
        try:
            if equity > self.portfolio_high:
                self.portfolio_high = equity
                log.debug(f"[HOCHSITZ] Neues Portfolio High: ${equity:.2f} - 100 Wallet aktualisiert")
        except Exception as e:
            log.debug(f"[HOCHSITZ] update_portfolio_high fail {e}")

    def find_last_green_candle_with_volume(self, ohlc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Letzte grüne Kerze mit Volumen - echter Hochsitz im Chart"""
        try:
            if not ohlc or 'close' not in ohlc or 'open' not in ohlc:
                return None
            closes = ohlc['close']
            opens = ohlc['open']
            volumes = ohlc.get('volume', [])
            highs = ohlc.get('high', [])
            
            if len(closes) < 5:
                return None
            
            # Suche rückwärts nach letzter grünen Kerze mit überdurchschnittlichem Volumen
            avg_vol = float(np.mean(volumes[-20:])) if len(volumes)>=20 else float(np.mean(volumes)) if volumes else 0
            
            for i in range(len(closes)-1, max(-1, len(closes)-20), -1):
                try:
                    if closes[i] > opens[i]:  # Grün
                        vol = volumes[i] if i < len(volumes) else 0
                        if vol >= avg_vol * 0.8:  # Mindestens 80% avg Volumen = valide
                            return {
                                "price": float(closes[i]),
                                "type": "green_candle_volume",
                                "index": i,
                                "volume": float(vol),
                                "timestamp": datetime.now().isoformat(),
                                "strength": float(vol / avg_vol) if avg_vol>0 else 1.0
                            }
                except:
                    continue
            return None
        except Exception as e:
            log.debug(f"[HOCHSITZ] find_last_green fail {e}")
            return None

    def get_anchor_for_symbol(self, symbol: str, current_price: float, ohlc: Optional[Dict], portfolio_high: Optional[float] = None) -> Dict[str, Any]:
        """Holt oder berechnet Hochsitz Anker für Symbol"""
        try:
            # 1. Versuche letzte grüne Kerze mit Volumen
            green = self.find_last_green_candle_with_volume(ohlc) if ohlc else None
            if green:
                anchor = {
                    "symbol": symbol,
                    "price": green["price"],
                    "type": green["type"],
                    "strength": green["strength"],
                    "volume": green["volume"],
                    "distance_pct": ((current_price - green["price"]) / green["price"] * 100) if green["price"]>0 else 0,
                    "timestamp": green["timestamp"],
                    "source": "chart"
                }
                self.anchors[symbol] = anchor
                log.debug(f"[HOCHSITZ][{symbol}] Anker grüne Kerze ${green['price']:.6f} Distanz {anchor['distance_pct']:.2f}%")
                return anchor
            
            # 2. Fallback: Portfolio High / 100 Wallet als Anker
            if portfolio_high and portfolio_high>0:
                # Portfolio High als psychologischer Anker
                anchor = {
                    "symbol": symbol,
                    "price": current_price * 1.02,  # Leichter Pull nach oben = Hochsitz
                    "type": "portfolio_high_proxy",
                    "strength": 0.5,
                    "distance_pct": 2.0,
                    "timestamp": datetime.now().isoformat(),
                    "source": "portfolio"
                }
                self.anchors[symbol] = anchor
                return anchor
            
            # 3. Letzter Anker oder aktueller Preis als Anker
            if symbol in self.anchors:
                old = self.anchors[symbol]
                # Update Distanz
                old["distance_pct"] = ((current_price - old["price"]) / old["price"] * 100) if old["price"]>0 else 0
                old["timestamp"] = datetime.now().isoformat()
                return old
            
            # 4. Notanker: aktueller Preis
            anchor = {
                "symbol": symbol,
                "price": current_price,
                "type": "current_price_anchor",
                "strength": 0.1,
                "distance_pct": 0.0,
                "timestamp": datetime.now().isoformat(),
                "source": "current"
            }
            self.anchors[symbol] = anchor
            return anchor
            
        except Exception as e:
            log.debug(f"[HOCHSITZ][{symbol}] get_anchor fail {e}")
            return {
                "symbol": symbol,
                "price": current_price,
                "type": "error_fallback",
                "strength": 0.1,
                "distance_pct": 0.0,
                "timestamp": datetime.now().isoformat(),
                "source": "error"
            }

def get_hochsitz_anchor(symbol: str, current_price: float, ohlc: Optional[Dict], state: Dict) -> Dict[str, Any]:
    """Helper für externen Zugriff"""
    try:
        engine = state.get("_hochsitz_engine")
        if not engine:
            engine = HochsitzAnchor()
            state["_hochsitz_engine"] = engine
        portfolio_high = state.get("equity", 0)
        return engine.get_anchor_for_symbol(symbol, current_price, ohlc, portfolio_high)
    except Exception as e:
        return {"symbol": symbol, "price": current_price, "type": "fallback", "distance_pct": 0}

def calculate_distance_to_hochsitz(current_price: float, hochsitz_price: float) -> float:
    """Distanz zum Hochsitz in %"""
    try:
        if hochsitz_price == 0:
            return 0.0
        return float((current_price - hochsitz_price) / hochsitz_price * 100)
    except:
        return 0.0
