"""
RINA RAKETE - FREEDOM & RECALL - Hirschgarten Prinzip

Dog Rina Rakete (Shiba Inu) bekommt 5 Minuten komplette Freiheit im Dickicht und kommt von selbst zurück.
Wir coden genau dieses Prinzip.

1. FREEDOM WINDOW (Free-Mode):
- Parameter: FREEDOM_WINDOW = 5 minutes (configurable 3-10min)
- Trigger: Position goes negative or enters thicket (high ATR + unclear structure + no clean fractal)
- During: NO SL, NO panic sell, NO intervention. Only log. Trust structure finds way back.

2. RECALL ANCHOR (Hochsitz):
- Fixed anchor: last clean portfolio high / 100 wallet / last green candle with volume
- Calculate distance_to_hochsitz, inner pull bias - longer free-mode = stronger weighting

3. ANTI-PANIC (rudi_atmet_durch):
- Human intervention blocked during Free-Mode
- block_user_intervention() for duration
- No manual closes, no SL changes. Hold like Rudi in forest.
- After expiry: soft recall with small adjustment ("Rina, hier"), no hard cut.

4. LOGIC:
IF position == in_thicket (ATR high + P/L <0 + no clear fractal)
  THEN start FREEDOM_WINDOW, block_user_intervention(), track distance
  IF time > FREEDOM_WINDOW AND not back THEN soft_recall
  ELSE IF back before expiry THEN log "Rina found the way" -> reinforce path
"""

import logging
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import traceback
import numpy as np

log = logging.getLogger("RINA_RAKETE")

# === CONFIG - Rina Rakete ===
FREEDOM_WINDOW_DEFAULT_MIN = 5  # Minuten, wie im Hirschgarten
FREEDOM_WINDOW_MIN = 3
FREEDOM_WINDOW_MAX = 10
ATR_HIGH_THRESHOLD = 0.025  # ATR > 2.5% vom Preis = high = Dickicht
BB_WIDE_THRESHOLD = 0.6  # BB Width >0.6 = unklare Struktur
RSI_UNCLEAR_LOW = 40
RSI_UNCLEAR_HIGH = 60

def is_in_thicket(position: Dict[str, Any], atr: Optional[float], bb_width: Optional[float], fractal: str, rsi: Optional[float]) -> Tuple[bool, str]:
    """
    Ist Position im Dickicht?
    Definition: high ATR + unclear structure + no clean fractal + P/L <0
    """
    try:
        pnl_pct = float(position.get("pnl_pct", 0) or position.get("pnl", 0) or 0)
        current_price = float(position.get("current_price", 0) or position.get("entry", 0) or 0)
        
        reasons = []
        thicket_score = 0
        
        # 1. P/L <0 = im Minus = im Dickicht
        if pnl_pct < 0:
            thicket_score += 1
            reasons.append(f"P/L {pnl_pct:.2f}% rot")
        
        # 2. ATR high = hohe Volatilität = dichtes Unterholz
        if atr is not None:
            try:
                atr_pct = (float(atr) / current_price * 100) if current_price>0 else 0
                if atr_pct > ATR_HIGH_THRESHOLD * 100 or float(atr) > current_price * ATR_HIGH_THRESHOLD:
                    thicket_score += 1
                    reasons.append(f"ATR high {atr_pct:.2f}% = dichtes Dickicht")
            except:
                pass
        else:
            # Wenn kein ATR, aber BB wide, auch Dickicht
            if bb_width and bb_width > BB_WIDE_THRESHOLD:
                thicket_score += 1
                reasons.append(f"BB {bb_width:.3f} wide = unklare Struktur")
        
        # 3. Unclear structure: BB wide OR RSI neutral ohne klares Fractal
        if bb_width is not None and bb_width > BB_WIDE_THRESHOLD:
            thicket_score += 1
            reasons.append(f"BB Width {bb_width:.3f} >{BB_WIDE_THRESHOLD} = keine Struktur")
        
        if rsi is not None:
            if RSI_UNCLEAR_LOW < float(rsi) < RSI_UNCLEAR_HIGH:
                # RSI neutral = unklar, aber nur wenn kein clean fractal
                if fractal in ["NEUTRAL", "ERROR", "INIT"] or "NEUTRAL" in fractal:
                    thicket_score += 1
                    reasons.append(f"RSI {rsi:.0f} neutral + fractal {fractal} = kein klares Bild")
        
        # 4. No clean fractal = kein Wegweiser im Wald
        if fractal in ["NEUTRAL", "ERROR", "INIT"] or not fractal or "NEUTRAL" in str(fractal):
            thicket_score += 1
            reasons.append(f"Fractal {fractal} = kein Wegweiser")
        
        is_thicket = thicket_score >= 2 and pnl_pct < 0  # Mindestens 2 Kriterien + rot
        
        reason_str = " + ".join(reasons) if reasons else "Kein Dickicht - klarer Weg"
        
        log.debug(f"[THICKET] {position.get('symbol','?')} thicket={is_thicket} score={thicket_score} {reason_str}")
        
        return is_thicket, reason_str
        
    except Exception as e:
        log.debug(f"[THICKET] check fail {e} {traceback.format_exc()}")
        return False, f"Error: {e}"

def calculate_distance_to_hochsitz(current_price: float, hochsitz_price: float) -> float:
    try:
        if hochsitz_price == 0 or current_price == 0:
            return 0.0
        return float((current_price - hochsitz_price) / hochsitz_price * 100)
    except:
        return 0.0

def get_hochsitz_anchor(symbol: str, current_price: float, ohlc: Optional[Dict], state: Dict) -> Dict[str, Any]:
    try:
        from .hochsitz import HochsitzAnchor
        # Engine im State cachen
        if "_hochsitz_engine" not in state:
            state["_hochsitz_engine"] = HochsitzAnchor()
        engine = state["_hochsitz_engine"]
        portfolio_high = state.get("equity", 0) or state.get("initial_equity_today", 0)
        return engine.get_anchor_for_symbol(symbol, current_price, ohlc, portfolio_high)
    except Exception as e:
        log.debug(f"[HOCHSITZ] get_anchor fail {e}")
        return {"symbol": symbol, "price": current_price, "type": "fallback", "distance_pct": 0, "timestamp": datetime.now().isoformat()}

class RinaRaketeEngine:
    """
    Rina Rakete - Freedom & Recall - Hirschgarten Berlin
    Shiba Inu 5 Minuten Freiheit im Dickicht, kommt von selbst zurück.
    """
    def __init__(self, freedom_window_min: int = FREEDOM_WINDOW_DEFAULT_MIN):
        self.freedom_window_min = max(FREEDOM_WINDOW_MIN, min(FREEDOM_WINDOW_MAX, freedom_window_min))
        self.freedom_windows: Dict[str, Dict[str, Any]] = {}  # symbol/call_id -> window data
        self.blocked_interventions: Dict[str, datetime] = {}  # call_id -> expiry
        self.reinforced_paths: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []
        log.info(f"[RINA] Rina Rakete Engine gestartet - Freedom Window {self.freedom_window_min}min - Hirschgarten Prinzip - Vertrauen statt Angst")

    def is_blocked(self, call_id: str) -> Tuple[bool, Optional[str]]:
        """Prüft ob User Intervention geblockt ist - rudi_atmet_durch"""
        try:
            if call_id in self.blocked_interventions:
                expiry = self.blocked_interventions[call_id]
                if datetime.now(ZoneInfo("Europe/Berlin")) < expiry:
                    remaining = (expiry - datetime.now(ZoneInfo("Europe/Berlin"))).total_seconds()
                    return True, f"Rina im Dickicht - Freedom Window noch {remaining/60:.1f}min - rudi_atmet_durch - kein manueller Close, kein SL Change - Vertrauen"
                else:
                    # Abgelaufen - entfernen
                    del self.blocked_interventions[call_id]
            return False, None
        except Exception as e:
            log.debug(f"[RINA] is_blocked fail {e}")
            return False, None

    def block_user_intervention(self, call_id: str, symbol: str, duration_min: Optional[int] = None) -> Dict[str, Any]:
        """Blockiert User Intervention für Freedom Window - Anti-Panic"""
        try:
            dur = duration_min or self.freedom_window_min
            dur = max(FREEDOM_WINDOW_MIN, min(FREEDOM_WINDOW_MAX, dur))
            expiry = datetime.now(ZoneInfo("Europe/Berlin")) + timedelta(minutes=dur)
            self.blocked_interventions[call_id] = expiry
            
            log_entry = {
                "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
                "symbol": symbol,
                "call_id": call_id,
                "action": "block_user_intervention",
                "duration_min": dur,
                "expiry": expiry.isoformat(),
                "message": f"Rina Rakete {symbol} ins Dickicht - {dur}min Freiheit - Rudi atmet durch - kein Eingriff",
                "type": "FREEDOM_START"
            }
            self.logs.append(log_entry)
            log.info(f"[RINA][{symbol}] 🐕 FREEDOM START {dur}min - block_user_intervention - Rudi atmet durch - kein Close, kein SL - Vertrauen")
            
            return log_entry
        except Exception as e:
            log.error(f"[RINA] block_user_intervention fail {e} {traceback.format_exc()}")
            return {"error": str(e)}

    def start_freedom_window(self, position: Dict[str, Any], hochsitz: Dict[str, Any], thicket_reason: str) -> Dict[str, Any]:
        """Startet Freedom Window wenn Position ins Dickicht geht"""
        try:
            symbol = position.get("symbol", "UNKNOWN")
            call_id = position.get("id", position.get("call_id", symbol))
            current_price = float(position.get("current_price", position.get("entry", 0)) or 0)
            
            # Bereits im Freedom?
            if call_id in self.freedom_windows:
                existing = self.freedom_windows[call_id]
                # Update Distanz
                dist = calculate_distance_to_hochsitz(current_price, hochsitz.get("price", current_price))
                existing["distance_to_hochsitz"] = dist
                existing["current_price"] = current_price
                existing["last_update"] = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
                log.debug(f"[RINA][{symbol}] bereits im Freedom - Distanz {dist:.2f}% zum Hochsitz")
                return existing
            
            start = datetime.now(ZoneInfo("Europe/Berlin"))
            expiry = start + timedelta(minutes=self.freedom_window_min)
            
            window = {
                "symbol": symbol,
                "call_id": call_id,
                "start": start.isoformat(),
                "expiry": expiry.isoformat(),
                "duration_min": self.freedom_window_min,
                "hochsitz": hochsitz,
                "hochsitz_price": hochsitz.get("price", current_price),
                "entry_price": float(position.get("entry", current_price)),
                "current_price": current_price,
                "distance_to_hochsitz": calculate_distance_to_hochsitz(current_price, hochsitz.get("price", current_price)),
                "thicket_reason": thicket_reason,
                "status": "FREEDOM",
                "logs": [],
                "reinforced": False
            }
            
            self.freedom_windows[call_id] = window
            self.block_user_intervention(call_id, symbol)
            
            log.info(f"[RINA][{symbol}] 🐕‍🦺 FREEDOM WINDOW START {self.freedom_window_min}min - Grund: {thicket_reason} - Hochsitz ${hochsitz.get('price',0):.6f} Distanz {window['distance_to_hochsitz']:.2f}% - Kein SL, kein Panic, nur loggen - Vertrauen dass Struktur zurückfindet")
            
            return window
            
        except Exception as e:
            log.error(f"[RINA] start_freedom_window fail {e} {traceback.format_exc()}")
            return {"error": str(e)}

    def check_freedom_windows(self, positions: List[Dict[str, Any]], state: Dict) -> List[Dict[str, Any]]:
        """Prüft alle aktiven Freedom Windows - Hirschgarten Logik"""
        try:
            now = datetime.now(ZoneInfo("Europe/Berlin"))
            results = []
            
            for call_id, window in list(self.freedom_windows.items()):
                try:
                    symbol = window["symbol"]
                    # Finde aktuelle Position
                    pos = next((p for p in positions if p.get("id")==call_id or p.get("symbol")==symbol), None)
                    if not pos:
                        # Position geschlossen - Window beenden
                        log.info(f"[RINA][{symbol}] Position nicht mehr da - Freedom Window beendet")
                        del self.freedom_windows[call_id]
                        if call_id in self.blocked_interventions:
                            del self.blocked_interventions[call_id]
                        continue
                    
                    current_price = float(pos.get("current_price", pos.get("entry", 0)) or 0)
                    pnl_pct = float(pos.get("pnl_pct", pos.get("pnl", 0)) or 0)
                    hochsitz_price = float(window["hochsitz_price"])
                    
                    # Distanz update
                    distance = calculate_distance_to_hochsitz(current_price, hochsitz_price)
                    window["distance_to_hochsitz"] = distance
                    window["current_price"] = current_price
                    window["pnl_pct"] = pnl_pct
                    window["last_update"] = now.isoformat()
                    
                    # Zeit prüfen
                    expiry = datetime.fromisoformat(window["expiry"])
                    time_left = (expiry - now).total_seconds()
                    elapsed_min = (now - datetime.fromisoformat(window["start"])).total_seconds() / 60
                    
                    # Innerer Sog zum Hochsitz - je länger im Free-Mode, desto stärker Gewichtung für Re-Entry
                    pull_strength = min(1.0, elapsed_min / self.freedom_window_min)  # 0..1
                    window["pull_strength"] = pull_strength
                    window["elapsed_min"] = elapsed_min
                    window["time_left_sec"] = time_left
                    
                    # Zurück zum Anker?
                    is_back = False
                    if abs(distance) < 1.0:  # <1% Distanz = zurück am Hochsitz
                        is_back = True
                    elif pnl_pct > 0 and distance < 2.0:  # Wieder grün + nah am Hochsitz
                        is_back = True
                    
                    if is_back and time_left > 0:
                        # Rina hat Weg zurück gefunden vor Ablauf!
                        window["status"] = "RINA_FOUND_WAY"
                        log_entry = {
                            "timestamp": now.isoformat(),
                            "symbol": symbol,
                            "action": "Rina found the way",
                            "elapsed_min": elapsed_min,
                            "distance": distance,
                            "pnl": pnl_pct,
                            "message": f"Rina Rakete {symbol} hat den Weg zurück gefunden nach {elapsed_min:.1f}min im Dickicht - Distanz {distance:.2f}% - Verstärke diesen Pfad für nächstes Mal - Vertrauen hat funktioniert - Hirschgarten"
                        }
                        window["logs"].append(log_entry)
                        self.logs.append(log_entry)
                        self.reinforced_paths.append({
                            "symbol": symbol,
                            "thicket_reason": window["thicket_reason"],
                            "elapsed_min": elapsed_min,
                            "distance": distance,
                            "timestamp": now.isoformat(),
                            "reinforced": True
                        })
                        log.info(f"[RINA][{symbol}] ✅ RINA FOUND THE WAY nach {elapsed_min:.1f}min - Distanz {distance:.2f}% P/L {pnl_pct:.2f}% - Verstärke Pfad - Vertrauen + Anker hat funktioniert")
                        
                        # Window beenden, Block entfernen
                        del self.freedom_windows[call_id]
                        if call_id in self.blocked_interventions:
                            del self.blocked_interventions[call_id]
                        results.append({"symbol": symbol, "result": "RINA_FOUND_WAY", "window": window})
                        continue
                    
                    # Zeit abgelaufen und nicht zurück?
                    if time_left <= 0 and not is_back:
                        # Soft Recall: partial secure, re-entry towards anchor
                        window["status"] = "SOFT_RECALL"
                        log_entry = {
                            "timestamp": now.isoformat(),
                            "symbol": symbol,
                            "action": "soft_recall",
                            "elapsed_min": elapsed_min,
                            "distance": distance,
                            "pnl": pnl_pct,
                            "pull_strength": pull_strength,
                            "message": f"Rina Rakete {symbol} nach {elapsed_min:.1f}min nicht zurück - Soft Recall - Distanz {distance:.2f}% - Pull {pull_strength:.2f} - Rina, hier! - kleine Positionsanpassung Richtung Hochsitz ${hochsitz_price:.6f}, kein harter Cut - Vertrauen + Anker"
                        }
                        window["logs"].append(log_entry)
                        self.logs.append(log_entry)
                        log.info(f"[RINA][{symbol}] 🔔 SOFT RECALL nach {elapsed_min:.1f}min - nicht zurück - Distanz {distance:.2f}% - Pull {pull_strength:.2f} - Rina, hier! - kleine Anpassung Richtung Hochsitz, kein harter Cut")
                        
                        # Soft Recall ausführen: Hier nur loggen, kein harter Close - in echter Trading Logik würde hier partial secure passieren
                        # Für V3.4.5: Nur loggen, Lafette gesichert = kein Auto Trading, aber Empfehlung für manuellen Soft Recall
                        results.append({"symbol": symbol, "result": "SOFT_RECALL", "window": window, "recommendation": f"Soft Recall Richtung Hochsitz ${hochsitz_price:.6f} - Pull {pull_strength:.2f} - kein harter Cut"})
                        
                        # Window beenden nach Soft Recall
                        del self.freedom_windows[call_id]
                        if call_id in self.blocked_interventions:
                            del self.blocked_interventions[call_id]
                        continue
                    
                    # Noch im Freedom Window - schnüffeln lassen
                    window["status"] = "FREEDOM_SNIFFING"
                    results.append({"symbol": symbol, "result": "FREEDOM_SNIFFING", "window": window})
                    log.debug(f"[RINA][{symbol}] Freedom sniffing {elapsed_min:.1f}/{self.freedom_window_min}min Distanz {distance:.2f}% Pull {pull_strength:.2f} - Rina schnüffelt im Dickicht - kein Eingriff")
                    
                except Exception as e:
                    log.error(f"[RINA] check window {call_id} fail {e} {traceback.format_exc()}")
                    continue
            
            return results
            
        except Exception as e:
            log.error(f"[RINA] check_freedom_windows fail {e} {traceback.format_exc()}")
            return []

    def get_status(self) -> Dict[str, Any]:
        try:
            now = datetime.now(ZoneInfo("Europe/Berlin"))
            active = []
            for call_id, w in self.freedom_windows.items():
                try:
                    expiry = datetime.fromisoformat(w["expiry"])
                    time_left = (expiry - now).total_seconds() / 60
                    active.append({
                        "symbol": w["symbol"],
                        "call_id": call_id,
                        "status": w["status"],
                        "elapsed_min": w.get("elapsed_min", 0),
                        "time_left_min": round(time_left,1),
                        "distance_to_hochsitz": w.get("distance_to_hochsitz", 0),
                        "pull_strength": w.get("pull_strength", 0),
                        "hochsitz_price": w.get("hochsitz_price", 0),
                        "thicket_reason": w.get("thicket_reason",""),
                        "pnl_pct": w.get("pnl_pct",0)
                    })
                except:
                    continue
            
            return {
                "version": "RINA RAKETE V1.0 - FREEDOM & RECALL - Hirschgarten Berlin",
                "freedom_window_min": self.freedom_window_min,
                "config": {"min": FREEDOM_WINDOW_MIN, "max": FREEDOM_WINDOW_MAX, "default": FREEDOM_WINDOW_DEFAULT_MIN, "atr_threshold": ATR_HIGH_THRESHOLD, "bb_threshold": BB_WIDE_THRESHOLD},
                "active_freedom_windows": active,
                "blocked_count": len(self.blocked_interventions),
                "blocked": [{"call_id": k, "expiry": v.isoformat(), "remaining_min": round((v-now).total_seconds()/60,1)} for k,v in self.blocked_interventions.items()],
                "reinforced_paths_count": len(self.reinforced_paths),
                "reinforced_paths": self.reinforced_paths[-10:],
                "logs_tail": self.logs[-20:],
                "quote": "Statt Angst im Dickicht, Vertrauen + Anker. Wie Rina im Hirschgarten - 5 Minuten Freiheit, kommt von selbst zurück.",
                "principle": "FREEDOM WINDOW = kein SL, kein Panic, nur loggen. RECALL ANCHOR = Hochsitz innerer Sog. ANTI-PANIC = rudi_atmet_durch block_user_intervention"
            }
        except Exception as e:
            log.error(f"[RINA] get_status fail {e} {traceback.format_exc()}")
            return {"error": str(e), "active_freedom_windows": []}
