"""
TURTLE V3.4.5 HUBBLE - SPLINTERCELL DICHT - MACHINE CODE MODE
HOLZ STEHT: Python + FastAPI + core.donatello + core.leonardo + core.splinter + core.moneyflow + connector
GELÄNDER SAFE: STABLECOIN_BLACKLIST, USDT-only, volume filter, dedupe, USDT.D + BTC.D
KEIN JAMES WEBB: simpel, robust, 34 Jahre flugfähig, wartbar
MASCHINENCODELASTIG: typisiert, json_safe, Lock, BackgroundScheduler, try/except traceback, logging DEBUG
NO AUTO TRADING V3.4.5 - nur Score. Lafette gesichert.
Quote: Birger Schäfermeier - "Nicht das beste Produkt, sondern die beste Geschichte gewinnt." -> story field
Quote2: "Wir suchen Shredders Fußsoldaten, jeden Tag werden genug geschreddert. Wir werden es nicht sein, denn wir sind Splintercell."
"""

import sys, os
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import logging
logging.basicConfig(level=logging.DEBUG, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
log = logging.getLogger("HUBBLE")
log.info(f"[BOOT] V3.4.5 HUBBLE ROOT={ROOT_DIR}")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Tuple
import traceback, json, numpy as np, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from threading import Lock
from apscheduler.schedulers.background import BackgroundScheduler
import requests

# === CORE IMPORTS - HOLZ STEHT ===
try:
    from core.donatello.persistent_state import load_state, save_state, log_day, DEFAULT_STATE
    from core.leonardo.reasoning import (
        get_market_data, check_filters, STABLECOIN_BLACKLIST,
        get_ohlc_three_windows, calc_atr, calc_bollinger_width, calc_rsi
    )
    from core.raphael.execution import open_position, monitor_positions, wizdraw_manual_close, close_position
    from core.splinter.turtle_scanner import TurtleScanner
    from core.splinter.cell import SplinterCell
    from core.moneyflow.scanner import MoneyFlowScanner
    from core.exchanges.connector import connector
    log.info(f"[BOOT] core OK exchanges={list(connector.exchanges.keys())}")
except Exception as e:
    log.error(f"[BOOT] core fail {e}\n{traceback.format_exc()}")
    raise

# === RINA RAKETE - SEPARATER TRY - FIXED SYNTAX - NICHT VERSCHACHTELT ===
RINA_AVAILABLE = False
try:
    from core.rina_rakete.freedom_recall import RinaRaketeEngine, is_in_thicket, get_hochsitz_anchor, calculate_distance_to_hochsitz
    from core.rina_rakete.hochsitz import HochsitzAnchor
    RINA_AVAILABLE = True
    log.info("[BOOT] Rina Rakete Module OK - Hirschgarten Prinzip")
except Exception as e:
    log.warning(f"[BOOT] Rina Fallback {e}")
    RINA_AVAILABLE = False
    from datetime import datetime as _dt
    class RinaRaketeEngine:
        def __init__(self, freedom_window_min=5):
            self.freedom_window_min=freedom_window_min
            self.freedom_windows={}
            self.blocked_interventions={}
            self.reinforced_paths=[]
            self.logs=[]
        def is_blocked(self, call_id):
            return False, None
        def block_user_intervention(self, call_id, symbol, duration_min=None):
            return {"blocked": False}
        def start_freedom_window(self, pos, hochsitz, reason):
            return {}
        def check_freedom_windows(self, positions, state):
            return []
        def get_status(self):
            return {"version":"RINA FALLBACK","active_freedom_windows":[],"freedom_window_min":self.freedom_window_min}
    def is_in_thicket(pos, atr, bb, fractal, rsi):
        return False, "Fallback"
    def get_hochsitz_anchor(sym, price, ohlc, state):
        return {"symbol": sym, "price": price, "type": "fallback", "distance_pct": 0}
    def calculate_distance_to_hochsitz(cur, hoch):
        return 0.0
    class HochsitzAnchor:
        def __init__(self):
            self.anchors={}
            self.portfolio_high=0
        def get_anchor_for_symbol(self, sym, price, ohlc, ph=None):
            return {"symbol": sym, "price": price, "type": "fallback", "distance_pct": 0}


try:
    from paper_trading_execution_V3_4 import PaperTradingExecutionV34
    log.info("[BOOT] PaperTradingExecutionV34 loaded")
except Exception as e:
    log.warning(f"[BOOT] Paper fallback {e}")
    class PaperTradingExecutionV34:
        def __init__(self):
            self.budget=100000; self.fee_pct=0.0004; self.slippage_pct=0.0002
            self.config={"max_exposure_usd":30000, "hubble_min_score":75}; self.logs=[]
        def get_leverage_for_score(self,s,b1,b4,u,f): return (4,"KURZ") if s>=10 else (3,"MITTEL") if s>=9 else (2,"MITTEL")
        def calculate_position_size(self,lev,score): return 3*lev, 100000*3*lev/100
        def get_time_stop_hours(self,mode,lev): return {"KURZ":4,"MITTEL":24,"LANG":168}.get(mode,24)/(lev/2)
        def should_auto_sell(self,pos): return False,"HOLD",{}
        def evaluate_paper_distribution(self,trades): return {}

app = FastAPI(title="TURTLE V3.4.6 HUBBLE + RINA RAKETE FIXED", version="3.4.6")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# === CONFIG - GELÄNDER SAFE ===
MAX_TRADES_PER_DAY=2
COOLDOWN_AFTER_TRADE_MIN=30
COOLDOWN_AFTER_LOSS_MIN=120
DAILY_PROFIT_TARGET_PCT=8.0
DAILY_LOSS_LIMIT_PCT=-4.0
BLACKLIST_START=99
BLACKLIST_END=99
BEST_START=0
BEST_END=24
BLACKLIST_TIME()
LOCK=Lock()
STATE=load_state()
BOOT_TIME=datetime.now(ZoneInfo("Europe/Berlin"))

# Ensure hubble keys in STATE
if "hubble_scores" not in STATE:
    STATE["hubble_scores"] = []
if "hubble_indices" not in STATE:
    STATE["hubble_indices"] = {"btc_dom": 52.5, "usdt_dom": 5.2, "last_update": None, "fractal": "INIT"}

HUBBLE_CFG: Dict[str, Any] = {
    "ath_dd_min": -70,
    "ath_dd_max": -40,
    "vol_dryup_pct": 0.4,
    "rsi_oversold": 38,
    "rsi_warning": 45,
    "days_down_min": 30,
    "hubble_min_score": 75,
    "btc_dom_bull": 52,
    "btc_dom_warn": 55,
    "cache_minutes": 15
}

def load_universe_100_fixed() -> List[str]:
    try:
        url="https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=volume_desc&per_page=100&page=1"
        log.debug(f"[UNIVERSE] fetching {url}")
        r=requests.get(url, timeout=15)
        j=r.json()
        if isinstance(j,list):
            uni=[f"{d['symbol'].upper()}USDT" for d in j if d.get('symbol') and d['symbol'].upper() not in STABLECOIN_BLACKLIST][:100]
            uni=[u for u in uni if u.endswith('USDT') and u[:-4] not in STABLECOIN_BLACKLIST]
            if len(uni)>=30:
                log.info(f"[UNIVERSE] loaded {len(uni)} from coingecko")
                return uni
    except Exception as e:
        log.warning(f"[UNIVERSE] fetch fail {e} {traceback.format_exc()}")
    fallback=["WIFUSDT","PEPEUSDT","BONKUSDT","FLOKIUSDT","POPCATUSDT","SHIBUSDT","DOGEUSDT","HYPEUSDT","SOLUSDT","AVAXUSDT","LINKUSDT","ARBUSDT","OPUSDT","APTUSDT","SUIUSDT","TIAUSDT","SEIUSDT","WUSDT","ENAUSDT","PENDLEUSDT","ONDOUSDT","RENDERUSDT","FETUSDT","TAOUSDT","WLDUSDT","STXUSDT","INJUSDT","RNDRUSDT","ARUSDT","LDOUSDT","MKRUSDT","RUNEUSDT","GRTUSDT","FLOWUSDT","NEARUSDT","ATOMUSDT","FILUSDT","HBARUSDT","VETUSDT","ALGOUSDT","QNTUSDT","EOSUSDT","XTZUSDT","EGLDUSDT","THETAUSDT","AAVEUSDT","KAVAUSDT","NEOUSDT","IOTAUSDT"]
    while len(fallback)<100:
        fallback.extend(fallback[:20])
    log.info(f"[UNIVERSE] fallback {len(fallback[:100])}")
    return fallback[:100]

UNIVERSE_100=load_universe_100_fixed()
turtle_scanner=TurtleScanner(UNIVERSE_100)
splinter_cell=SplinterCell()
moneyflow_scanner=MoneyFlowScanner()
paper_executor=PaperTradingExecutionV34()

def json_safe(obj: Any) -> Any:
    try:
        if isinstance(obj,(np.bool_,bool)): return bool(obj)
        if isinstance(obj,(np.integer,)): return int(obj)
        if isinstance(obj,(np.floating,)): return float(obj)
        if isinstance(obj,np.ndarray): return obj.tolist()
        if isinstance(obj,dict): return {k:json_safe(v) for k,v in obj.items()}
        if isinstance(obj,(list,tuple)): return [json_safe(x) for x in obj]
        if hasattr(obj,'__dict__'): return json_safe(obj.__dict__)
        return obj
    except Exception as e:
        log.debug(f"[json_safe] fail {e} for {type(obj)}")
        return str(obj)

def get_current_whitelist() -> List[str]:
    try:
        dyn=STATE.get("dynamic_whitelist")
        if dyn and len(dyn)>=5:
            filtered=[s for s in dyn if s[:-4] not in STABLECOIN_BLACKLIST and s.endswith('USDT')]
            if len(filtered)>=5:
                return filtered
            return filtered + [x for x in UNIVERSE_100 if x not in filtered][:8-len(filtered)]
        return UNIVERSE_100[:20]
    except Exception as e:
        log.error(f"[whitelist] fail {e}")
        return UNIVERSE_100[:20]

class PoolPayload(BaseModel):
    pool:List[str]
    details:Optional[List[dict]]=None

def is_blacklist_time() -> Tuple[bool,str]:
    try:
        h=datetime.now(ZoneInfo("Europe/Berlin")).hour
        if h>=BLACKLIST_START or h<BLACKLIST_END:
            return True,f"BLACKLIST {h}:00 CET - Shredder jagt nachts"
        return False,""
    except Exception as e:
        log.error(f"[blacklist_time] {e}")
        return False,""

def is_best_time() -> bool:
    try:
        return BEST_START <= datetime.now(ZoneInfo("Europe/Berlin")).hour < BEST_END
    except:
        return False

def check_daily_reset():
    global STATE
    try:
        today=datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
        if STATE.get("last_reset_date")!=today:
            try:
                log_day({"date":STATE.get("last_reset_date"),"trades":STATE.get("trades_today"),"pnl_pct":STATE.get("daily_pnl_pct"),"equity_end":STATE.get("equity")})
            except Exception as e:
                log.debug(f"[daily_reset] log_day fail {e}")
            STATE["initial_equity_today"]=STATE.get("equity",0)
            STATE["daily_pnl_pct"]=0; STATE["daily_pnl_usd"]=0; STATE["trades_today"]=0
            STATE["closed_today"]=[]; STATE["status"]="JAGT"; STATE["status_reason"]="Neuer Tag - Splintercell bereit"; STATE["last_reset_date"]=today
            save_state(STATE)
            log.info(f"[RESET] new day {today}")
    except Exception as e:
        log.error(f"[check_daily_reset] {e} {traceback.format_exc()}")

def update_status():
    global STATE
    try:
        check_daily_reset()
        if STATE.get("daily_pnl_pct",0)>=DAILY_PROFIT_TARGET_PCT:
            STATE["status"]="FEIERABEND_GEWINN"; STATE["status_reason"]=f"Target +{DAILY_PROFIT_TARGET_PCT}% - Feierabend"
            return
        if STATE.get("daily_pnl_pct",0)<=DAILY_LOSS_LIMIT_PCT:
            STATE["status"]="FEIERABEND_SCHUTZ"; STATE["status_reason"]=f"Loss {DAILY_LOSS_LIMIT_PCT}% - Schutz"
            return
        if STATE.get("trades_today",0)>=MAX_TRADES_PER_DAY:
            STATE["status"]="FEIERABEND_GEWINN"; STATE["status_reason"]=f"Max {MAX_TRADES_PER_DAY} Trades - Dicht"
            return
        now=datetime.now(ZoneInfo("Europe/Berlin"))
        if STATE.get("last_loss_time"):
            try:
                last_loss=datetime.fromisoformat(STATE["last_loss_time"])
                if (now-last_loss).total_seconds()<COOLDOWN_AFTER_LOSS_MIN*60:
                    STATE["status"]="PAUSE"; STATE["status_reason"]=f"Anti-Revenge {COOLDOWN_AFTER_LOSS_MIN}m - Dicht bleiben"
                    return
            except Exception as e:
                log.debug(f"[update_status] last_loss parse {e}")
        if STATE.get("last_trade_end"):
            try:
                last_end=datetime.fromisoformat(STATE["last_trade_end"])
                if (now-last_end).total_seconds()<COOLDOWN_AFTER_TRADE_MIN*60:
                    STATE["status"]="PAUSE"; STATE["status_reason"]=f"Cooldown {COOLDOWN_AFTER_TRADE_MIN}m"
                    return
            except Exception as e:
                log.debug(f"[update_status] last_trade parse {e}")
        is_black,reason=is_blacklist_time()
        if is_black:
            STATE["status"]="PAUSE"; STATE["status_reason"]=reason; return
        STATE["status"]="JAGT"; STATE["status_reason"]="Splintercell jagt - Shredders Fußsoldaten gesucht"
    except Exception as e:
        log.error(f"[update_status] {e} {traceback.format_exc()}")
        STATE["status"]="JAGT"; STATE["status_reason"]=f"Error fallback JAGT: {e}"

def paper_monitor_positions():
    try:
        with LOCK:
            if not STATE.get("open_positions"):
                return
            for pos in list(STATE.get("open_positions",[])):
                try:
                    should_sell, reason, meta = paper_executor.should_auto_sell(pos)
                    if should_sell:
                        log.info(f"[PAPER] auto sell {pos.get('symbol')} {reason}")
                except Exception as e:
                    log.debug(f"[paper_monitor] {e}")
    except Exception as e:
        log.error(f"[paper_monitor_positions] {e} {traceback.format_exc()}")

# === HUBBLE ENGINE - DICHT - 34 JAHRE FLUGFÄHIG ===
class HubbleEngine:
    def __init__(self):
        self.indices_cache: Dict[str, Any] = {"btc_dom": 52.5, "usdt_dom": 5.2, "btc_dom_change": 0.0, "last_update": None, "fractal": "INIT", "source": "cache"}
        self.last_fetch: Optional[datetime] = None
        log.info("[HUBBLE] Engine init - Hubble wartet auf Tiefenblick")

    def fetch_indices(self) -> Dict[str, Any]:
        try:
            # Cache 15min
            if self.last_fetch and (datetime.now() - self.last_fetch).total_seconds() < HUBBLE_CFG["cache_minutes"]*60:
                log.debug(f"[HUBBLE] indices cache hit btc_dom={self.indices_cache['btc_dom']} age={(datetime.now()-self.last_fetch).total_seconds()/60:.1f}m")
                return self.indices_cache

            log.info("[HUBBLE] fetching indices from coingecko global")
            url = "https://api.coingecko.com/api/v3/global"
            r = requests.get(url, timeout=12)
            j = r.json()
            data = j.get("data",{})
            mcap_pct = data.get("market_cap_percentage",{})
            btc_dom = float(mcap_pct.get("btc", self.indices_cache["btc_dom"]))
            usdt_dom = float(mcap_pct.get("usdt", self.indices_cache["usdt_dom"]))

            prev_btc = self.indices_cache.get("btc_dom", btc_dom)
            btc_change = btc_dom - prev_btc

            fractal = "NEUTRAL"
            if btc_dom < 52:
                fractal = "BTC.D FALLING + ALT PUMP SETUP" if btc_change < 0 else "BTC.D LOW - ALT FENSTER OFFEN"
            elif btc_dom > 55:
                fractal = "BTC.D HIGH - BTC DOMINIERT - VORSICHT ALTS"
            else:
                fractal = "BTC.D NEUTRAL - SELECTIVE ALT CHANCE"

            self.indices_cache.update({
                "btc_dom": round(btc_dom,2),
                "usdt_dom": round(usdt_dom,2),
                "btc_dom_change": round(btc_change,3),
                "last_update": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
                "fractal": fractal,
                "source": "coingecko"
            })
            self.last_fetch = datetime.now()
            
            with LOCK:
                STATE["hubble_indices"] = self.indices_cache.copy()
                save_state(STATE)

            log.info(f"[HUBBLE] indices OK btc_dom={btc_dom:.2f}% usdt_dom={usdt_dom:.2f}% fractal={fractal}")
            return self.indices_cache

        except Exception as e:
            log.warning(f"[HUBBLE] indices fetch fail {e} - use cache btc_dom={self.indices_cache['btc_dom']}")
            log.debug(traceback.format_exc())
            return self.indices_cache

    def calc_hubble_score(self, symbol: str, item: Dict[str,Any], ohlc_24h: Optional[Dict], ohlc_30d: Optional[Dict], ohlc_180d: Optional[Dict], atr: Optional[float], bb_width: Optional[float], rsi: Optional[float], mf_signal: Dict[str,Any]) -> Dict[str, Any]:
        """
        Hubble Score 0-100 - simpel, robust, 34 Jahre flugfähig
        Birger Schäfermeier: "Nicht das beste Produkt, sondern die beste Geschichte gewinnt." -> story field
        """
        try:
            score = 0
            bonus = 0
            fractal = "NEUTRAL"
            story_parts: List[str] = []
            
            # === PREP ===
            curr_price = float(item.get("price", 0) or item.get("current_price", 0) or 0)
            change_24h = float(item.get("change", 0) or item.get("change_24h", 0) or 0)
            turtle_score = float(item.get("score", 0) or item.get("turtle_score", 0) or 0)

            # ATH DD
            ath_dd = float(item.get("ath_dd", -20))
            try:
                if ohlc_180d is not None and 'high' in ohlc_180d and len(ohlc_180d['high'])>0:
                    ath = float(np.max(ohlc_180d['high']))
                    if ath>0 and curr_price>0:
                        ath_dd = (curr_price - ath)/ath*100
            except Exception as e:
                log.debug(f"[HUBBLE][{symbol}] ath_dd calc fail {e}")

            # Days down proxy - wie lange blutet der FootSoldat?
            days_down_proxy = int(abs(ath_dd) * 1.2) if ath_dd<0 else 0
            try:
                if ohlc_180d and 'close' in ohlc_180d:
                    closes = ohlc_180d['close']
                    if len(closes)>10:
                        # Zähle Tage unter 0.9*ATH als "down"
                        ath = float(np.max(ohlc_180d['high'])) if 'high' in ohlc_180d else curr_price*1.5
                        down_days = sum(1 for c in closes if c < ath*0.9)
                        days_down_proxy = max(days_down_proxy, down_days)
            except:
                pass

            # BB Width, ATR, RSI defaults
            bb_width = float(bb_width) if bb_width is not None else 0.5
            atr = float(atr) if atr is not None else 0.0
            rsi = float(rsi) if rsi is not None else 50.0

            # Indices
            btc_dom = float(self.indices_cache.get("btc_dom", 52.5))
            usdt_dom = float(self.indices_cache.get("usdt_dom", 5.2))
            mf_verdict = str(mf_signal.get("verdict", "NEUTRAL") if isinstance(mf_signal, dict) else "NEUTRAL")
            mf_ok = mf_verdict in ["GUT","NEUTRAL"] or "GUT" in mf_verdict

            # === SCORE LOGIC - HUBBLE ===
            # 1. ATH_DD -40 bis -70 = +30 (sweet spot: genug geschreddert, aber nicht tot)
            if HUBBLE_CFG["ath_dd_max"] >= ath_dd >= HUBBLE_CFG["ath_dd_min"]:
                score += 30
                story_parts.append(f"{ath_dd:.0f}% vom ATH - Sweet Spot")
            elif ath_dd < HUBBLE_CFG["ath_dd_min"]:
                score += 15
                story_parts.append(f"{ath_dd:.0f}% tief geschreddert - Rebound Chance")
            else:
                story_parts.append(f"{ath_dd:.0f}% ATH - noch zu hoch")

            # 2. Days Down >=30 = +20 (genug geblutet)
            if days_down_proxy >= HUBBLE_CFG["days_down_min"]:
                score += 20
                story_parts.append(f"seit {days_down_proxy}T am Bluten")
            else:
                story_parts.append(f"nur {days_down_proxy}T down")

            # 3. Vol Dryup: bb_width <0.4 OR (abs(vol24)<3 AND 35<rsi<65) = +20
            dryup_ok = False
            if bb_width < HUBBLE_CFG["vol_dryup_pct"]:
                score += 20
                dryup_ok = True
                story_parts.append(f"BB {bb_width:.2f} eng wie Splinterzelle")
            else:
                if abs(change_24h) < 3 and 35 < rsi < 65:
                    score += 15
                    dryup_ok = True
                    story_parts.append(f"Vol trocken {change_24h:.1f}% + RSI {rsi:.0f} neutral")
                else:
                    story_parts.append(f"BB {bb_width:.2f} noch weit")

            # 4. RSI <38 = +10 else <45 = +5 (überverkauft)
            if rsi < HUBBLE_CFG["rsi_oversold"]:
                score += 10
                story_parts.append(f"RSI {rsi:.0f} überverkauft")
            elif rsi < HUBBLE_CFG["rsi_warning"]:
                score += 5
                story_parts.append(f"RSI {rsi:.0f} schwach")
            else:
                story_parts.append(f"RSI {rsi:.0f}")

            # 5. BTC.D + MF Fractal
            if btc_dom < HUBBLE_CFG["btc_dom_bull"] and mf_ok:
                score += 15
                fractal = "BTC.D FALLING + MF GUT = ALT PUMP SETUP"
                story_parts.append(f"BTC.D {btc_dom:.1f}% fällt + MF {mf_verdict} = Alt Pump")
            elif btc_dom < HUBBLE_CFG["btc_dom_warn"]:
                score += 8
                fractal = "BTC.D LOW - ALT FENSTER OFFEN"
                story_parts.append(f"BTC.D {btc_dom:.1f}% low - Fenster offen")
            else:
                fractal = "BTC.D HIGH - BTC dominiert"
                story_parts.append(f"BTC.D {btc_dom:.1f}% hoch - BTC dominiert")

            # 6. Best TimeWindow 9-15 CET = +5
            # hour = datetime.now(ZoneInfo("Europe/Berlin")).hour
            # timewindow = f"{hour:02d}:00 CET"
            # if BEST_START <= hour < BEST_END:
            #    score += 5
            #    bonus += 5
            #    story_parts.append(f"{timewindow} BEST Time")
            #else:
            #    story_parts.append(f"{timewindow}")

            # Clamp 0-100
            score = max(0, min(100, score))

            # Ready?
            ready = score >= HUBBLE_CFG["hubble_min_score"]

            # Story bauen - Birger Schäfermeier: Geschichte gewinnt
            story = f"{symbol.replace('USDT','')} ist {ath_dd:.0f}% vom ATH, {days_down_proxy}T am Bluten, BB {bb_width:.2f} eng, RSI {rsi:.0f}, BTC.D {btc_dom:.1f}% {mf_verdict}. {' • '.join(story_parts[:4])}. Score {score} - {'READY - FootSoldat gefunden' if ready else 'WAIT - noch nicht dicht genug'} - Splintercell sucht Shredders Fußsoldaten, jeden Tag werden genug geschreddert. Wir werden es nicht sein."

            # Short story for table
            short_story = f"{ath_dd:.0f}% ATH, {days_down_proxy}T, RSI {rsi:.0f}, {fractal[:30]}"

            result = {
                "symbol": symbol,
                "score": int(score),
                "ready": bool(ready),
                "ath_dd": round(float(ath_dd),2),
                "days_down_proxy": int(days_down_proxy),
                "bb_width": round(float(bb_width),4) if bb_width else None,
                "atr": round(float(atr),6) if atr else None,
                "rsi": round(float(rsi),2) if rsi else None,
                "btc_dom": round(float(btc_dom),2),
                "usdt_dom": round(float(usdt_dom),2),
                "mf_verdict": mf_verdict,
                "fractal": fractal,
                "story": story,
                "short_story": short_story,
                "timewindow": timewindow,
                "bonus": bonus,
                "dryup_ok": dryup_ok,
                "turtle_score": round(float(turtle_score),2),
                "change_24h": round(float(change_24h),2),
                "price": curr_price,
                "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
                "config": {"min_score": HUBBLE_CFG["hubble_min_score"], "ath_range": [HUBBLE_CFG["ath_dd_min"], HUBBLE_CFG["ath_dd_max"]]}
            }

            log.debug(f"[HUBBLE][{symbol}] score={score} ready={ready} ath_dd={ath_dd:.1f}% rsi={rsi:.0f} btc_dom={btc_dom:.1f}% fractal={fractal}")

            return json_safe(result)

        except Exception as e:
            log.error(f"[HUBBLE][{symbol}] calc fail {e} {traceback.format_exc()}")
            return {
                "symbol": symbol, "score": 0, "ready": False,
                "ath_dd": -20, "days_down_proxy": 0, "bb_width": None, "rsi": 50,
                "btc_dom": self.indices_cache.get("btc_dom",52.5), "mf_verdict": "ERROR",
                "fractal": "ERROR", "story": f"{symbol} - Error {e} - Splintercell bleibt dicht", "short_story": f"Error {e}",
                "timewindow": datetime.now(ZoneInfo("Europe/Berlin")).strftime("%H:%M"), "bonus":0, "turtle_score":0, "change_24h":0, "price":0,
                "timestamp": datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
            }

hubble_engine = HubbleEngine()

# === TURTLE + SPLINTER - HOLZ STEHT ===
def run_turtle_scan():
    global STATE
    try:
        log.info("[TURTLE] scan start 100 -> 20")
        with LOCK:
            update_status()
            if STATE.get("status")!="JAGT":
                log.info(f"[TURTLE] skip status={STATE.get('status')}")
                return STATE.get("vorauswahl_queue",[])
            results = turtle_scanner.scan_once(get_market_data)
            STATE["vorauswahl_queue"] = results[:20]
            STATE["vorauswahl_queue"] = results[:20]
            STATE["dynamic_whitelist"] = [r["symbol"] if isinstance(r, dict) else r for r in results[:20]]
            save_state(STATE)
            log.info(f"[TURTLE] done queue={len(results[:20])} {STATE['dynamic_whitelist'][:3]}")
            return results
    except Exception as e:
        log.error(f"[TURTLE] fail {e} {traceback.format_exc()}")
        return []

def run_splinter_inspection():
    global STATE
    try:
        log.info("[SPLINTER] inspection start")
        with LOCK:
            queue = STATE.get("vorauswahl_queue",[])[:8]
            if not queue:
                log.info("[SPLINTER] queue empty, skip")
                return []
            inspection_results=[]
            for item in queue:
                try:
                    sym = item["symbol"] if isinstance(item, dict) else item
                    data = get_market_data(sym)
                    if data.get("price",0)==0:
                        continue
                    ok,checks,meta = check_filters(sym, data, [])
                    inspection_results.append(json_safe({"symbol":sym,"ok":bool(ok),"checks":checks,"meta":meta,"price":float(data.get("price",0)),"change_24h":float(data.get("price_change_24h",0))}))
                except Exception as e:
                    log.debug(f"[SPLINTER] {sym} fail {e}")
                    continue
                time.sleep(0.3)
            STATE["splinter_inspection"]=inspection_results
            save_state(STATE)
            log.info(f"[SPLINTER] done {len(inspection_results)}")
            return inspection_results
    except Exception as e:
        log.error(f"[SPLINTER] fail {e} {traceback.format_exc()}")
        return []

def run_hubble_inspection():
    global STATE
    try:
        log.info("[HUBBLE] deep dive start top8")
        with LOCK:
            queue = STATE.get("vorauswahl_queue",[])[:8]
            if not queue:
                log.info("[HUBBLE] queue empty, skip")
                return []
            
            # Fetch indices + moneyflow
            indices = hubble_engine.fetch_indices()
            try:
                mf = moneyflow_scanner.scan() if hasattr(moneyflow_scanner, 'scan') else {}
                if isinstance(mf, dict):
                    STATE["money_flow"] = mf
            except Exception as e:
                log.debug(f"[HUBBLE] moneyflow scan fail {e}")
                mf = STATE.get("money_flow",{})

            mf_signal = {"verdict": mf.get("verdict","NEUTRAL") if isinstance(mf, dict) else "NEUTRAL", "ok_for_short": mf.get("avg_vol_change",0)<0 if isinstance(mf, dict) else True}

            hubble_results=[]
            for item in queue:
                try:
                    sym = item["symbol"] if isinstance(item, dict) else item
                    log.debug(f"[HUBBLE] calc {sym}")
                    data = get_market_data(sym)
                    ohlc_24h, ohlc_30d, ohlc_180d = None, None, None
                    atr, bb_width, rsi = None, None, None
                    try:
                        ohlc_24h, ohlc_30d, ohlc_180d = get_ohlc_three_windows(sym)
                        if ohlc_24h:
                            closes = ohlc_24h.get('close',[])
                            if len(closes)>0:
                                atr = calc_atr(ohlc_24h) if 'high' in ohlc_24h else None
                                bb_width = calc_bollinger_width(ohlc_24h)
                                rsi = calc_rsi(closes)
                    except Exception as e:
                        log.debug(f"[HUBBLE] ohlc calc {sym} fail {e}")

                    # item dict for score
                    item_dict = item if isinstance(item, dict) else {"symbol":sym, "price": data.get("price",0), "change": data.get("price_change_24h",0), "ath_dd": -30}

                    score_dict = hubble_engine.calc_hubble_score(sym, item_dict, ohlc_24h, ohlc_30d, ohlc_180d, atr, bb_width, rsi, mf_signal)
                    hubble_results.append(score_dict)

                except Exception as e:
                    log.error(f"[HUBBLE] {sym} calc fail {e} {traceback.format_exc()}")
                    continue
                time.sleep(0.4)

            hubble_results_sorted = sorted(hubble_results, key=lambda x: x.get("score",0), reverse=True)
            STATE["hubble_scores"] = hubble_results_sorted
            STATE["hubble_indices"] = indices
            save_state(STATE)
            top_ready = [h for h in hubble_results_sorted if h.get("ready")]
            log.info(f"[HUBBLE] done {len(hubble_results_sorted)} scores, ready={len(top_ready)} top={hubble_results_sorted[0].get('symbol') if hubble_results_sorted else 'none'} score={hubble_results_sorted[0].get('score') if hubble_results_sorted else 0}")
            return hubble_results_sorted

    except Exception as e:
        log.error(f"[HUBBLE] inspection fail {e} {traceback.format_exc()}")
        return []

def scan_all():
    global STATE
    try:
        update_status()
        whitelist=get_current_whitelist()
        if STATE["status"]!="JAGT":
            return json_safe({"status":STATE["status"],"reason":STATE["status_reason"],"results":[],"whitelist":whitelist})
        open_syms=[p["symbol"] for p in STATE.get("open_positions",[])]
        results=[]
        for sym in whitelist[:20]:
            try:
                data=get_market_data(sym)
                if data["price"]==0: continue
                ok,checks,meta=check_filters(sym,data,open_syms)
                results.append(json_safe({"symbol":sym,"ok":bool(ok),"checks":checks,"meta":meta,"price":float(data.get("price",0)),"change_24h":float(data.get("price_change_24h",0)),"source":str(data.get("source","none"))}))
            except Exception as ex:
                log.debug(f"[scan_all] {sym} fail {ex}")
                results.append(json_safe({"symbol":sym,"ok":False,"price":0}))
            time.sleep(0.2)
        return json_safe({"status":STATE["status"],"reason":STATE["status_reason"],"results":results,"whitelist":whitelist})
    except Exception as e:
        log.error(f"[scan_all] {e} {traceback.format_exc()}")
        return json_safe({"status":"ERROR","reason":str(e),"results":[],"whitelist":get_current_whitelist()})

# === HEALTH FÜR UPTIMEROBOT - SUPER SCHNELL OHNE LOCK ===
from datetime import datetime

BOOT_TIME = datetime.utcnow()  # falls nicht schon vorhanden

@app.get("/health")
@app.get("/api/v34/health")
@app.get("/ping")
async def health():
    return {"status": "ok", "version": "3.4.6", "mode": "JAGT", "uptime": int((datetime.utcnow() - BOOT_TIME).total_seconds())}

@app.get("/ping")
def ping():
    return {"status":"online","ping":"pong","ts":datetime.utcnow().isoformat(),"version":"V3.4.5 HUBBLE"}

# === DASHBOARD - ROOT = DASHBOARD DICHT ===
@app.get("/", response_class=HTMLResponse)
def root_dashboard():
    try:
        # Try hubble dashboard first, then old
        for tmpl in ["templates/dashboard_v34_hubble.html", "templates/dashboard_v34.html"]:
            tmpl_path = os.path.join(os.path.dirname(__file__), tmpl)
            if os.path.exists(tmpl_path):
                with open(tmpl_path, "r", encoding="utf-8") as f:
                    html = f.read()
                log.debug(f"[DASHBOARD] serving {tmpl}")
                return HTMLResponse(html)
    except Exception as e:
        log.error(f"[DASHBOARD] template fail {e} {traceback.format_exc()}")
    # Fallback minimal DICHT
    try:
        with LOCK:
            equity=STATE.get("equity",0)
            hubble_len=len(STATE.get("hubble_scores",[]))
            ready_len=len([h for h in STATE.get("hubble_scores",[]) if h.get("ready")])
            status=STATE.get("status","JAGT")
        uptime=int((datetime.now(ZoneInfo("Europe/Berlin"))-BOOT_TIME).total_seconds())
        return HTMLResponse(f"""
        <html><head><title>TURTLE V3.4.5 HUBBLE DICHT</title>
        <style>body{{background:#070707;color:#eee;font-family:monospace;padding:20px}} .card{{border:1px solid #39ff14;padding:15px;margin:10px 0;border-radius:8px}} a{{color:#39ff14}} .ready{{background:#39ff14;color:#000;padding:2px 8px;border-radius:10px}}</style>
        </head><body>
        <h1>🐢🔭 TURTLE V3.4.5 HUBBLE // SPLINTERCELL DICHT</h1>
        <div class="card">Status: {status} | Equity: ${equity:.2f} | Hubble: {hubble_len} | Ready: <span class="ready">{ready_len}</span> | Uptime: {uptime}s<br>
        HOLZ STEHT • GELÄNDER SAFE • NO AUTO TRADING • LAFETTE GESICHERT<br>
        Wir suchen Shredders Fußsoldaten, jeden Tag werden genug geschreddert. Wir werden es nicht sein, denn wir sind Splintercell.</div>
        <div class="card"><b>API:</b><br>
        <a href="/api/v34/health">/api/v34/health</a> - Health für UptimeRobot<br>
        <a href="/api/v34/hubble">/api/v34/hubble</a> - Hubble Scores (main)<br>
        <a href="/api/v34/debug">/api/v34/debug</a> - Debug raw<br>
        <a href="/api/v34/turtles">/api/v34/turtles</a> - Turtle Queue<br>
        <a href="/api/v34/splinter">/api/v34/splinter</a> - Splinter<br>
        <a href="/api/v34/moneyflow">/api/v34/moneyflow</a> - MoneyFlow<br>
        <a href="/dashboard">/dashboard</a> - Dashboard<br>
        <a href="/health">/health</a> • <a href="/ping">/ping</a>
        </div>
        <div class="card" id="live">Loading Hubble...</div>
        <script>
        async function load(){{
          try{{
            let r=await fetch('/api/v34/hubble'); let j=await r.json();
            let top=j.top_ready||[]; let scores=j.scores||[];
            document.getElementById('live').innerHTML=`Hubble: ${{scores.length}} scores, Ready: ${{top.length}}<br>Indices: BTC.D ${{j.indices?.btc_dom}}% | USDT.D ${{j.indices?.usdt_dom}}% | ${{j.indices?.fractal}}<br>Top: ${{scores.slice(0,3).map(s=>s.symbol+':'+s.score).join(', ')}}`;
          }}catch(e){{document.getElementById('live').innerHTML='Error: '+e}}
        }}
        setInterval(load,30000); load();
        </script>
        </body></html>
        """)
    except Exception as e:
        log.error(f"[root_dashboard] fallback fail {e}")
        return HTMLResponse(f"<html><body><h1>HUBBLE DICHT - Error {e}</h1></body></html>")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_alias():
    return root_dashboard()

@app.get("/api/v34/turtles")
def api_turtles():
    try:
        with LOCK:
            return JSONResponse(json_safe({"queue":STATE.get("vorauswahl_queue",[]),"count":len(STATE.get("vorauswahl_queue",[])),"universe_size":len(UNIVERSE_100)}))
    except Exception as e:
        log.error(f"[api_turtles] {e}")
        return JSONResponse({"queue":[],"count":0,"error":str(e)})

@app.get("/api/v34/splinter")
def api_splinter():
    try:
        with LOCK:
            return JSONResponse(json_safe({"inspection":STATE.get("splinter_inspection",[])}))
    except Exception as e:
        log.error(f"[api_splinter] {e}")
        return JSONResponse({"inspection":[],"error":str(e)})

@app.get("/api/v34/hubble")
def api_hubble():
    try:
        with LOCK:
            scores=STATE.get("hubble_scores",[])
            sorted_scores=sorted(scores, key=lambda x: x.get("score",0), reverse=True)
            top_ready=[s for s in sorted_scores if s.get("ready")]
            indices=STATE.get("hubble_indices", hubble_engine.indices_cache)
            return JSONResponse(json_safe({
                "version":"V3.4.5 HUBBLE DICHT",
                "timestamp":datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
                "indices":indices,
                "config":HUBBLE_CFG,
                "scores":sorted_scores,
                "top_ready":top_ready,
                "count":len(scores),
                "ready_count":len(top_ready),
                "quote":"Nicht das beste Produkt, sondern die beste Geschichte gewinnt. - Birger Schäfermeier",
                "quote2":"Wir suchen Shredders Fußsoldaten, jeden Tag werden genug geschreddert. Wir werden es nicht sein, denn wir sind Splintercell."
            }))
    except Exception as e:
        log.error(f"[api_hubble] {e} {traceback.format_exc()}")
        return JSONResponse({"scores":[],"top_ready":[],"error":str(e)}, status_code=500)

@app.get("/api/v34/debug")
def api_debug():
    try:
        with LOCK:
            return JSONResponse(json_safe({
                "boot":BOOT_TIME.isoformat(),
                "uptime_sec":int((datetime.now(ZoneInfo("Europe/Berlin"))-BOOT_TIME).total_seconds()),
                "state_keys":list(STATE.keys()),
                "universe":UNIVERSE_100[:15],
                "universe_count":len(UNIVERSE_100),
                "turtle_queue":STATE.get("vorauswahl_queue",[])[:5],
                "hubble":STATE.get("hubble_scores",[])[:5],
                "hubble_count":len(STATE.get("hubble_scores",[])),
                "moneyflow":STATE.get("money_flow",{}),
                "indices":STATE.get("hubble_indices", hubble_engine.indices_cache),
                "status":STATE.get("status"),
                "equity":STATE.get("equity"),
                "logs_tail":paper_executor.logs[-20:] if hasattr(paper_executor,'logs') else [],
                "config":HUBBLE_CFG,
                "mode":"NO AUTO TRADING - SCORE ONLY"
            }))
    except Exception as e:
        log.error(f"[api_debug] {e} {traceback.format_exc()}")
        return JSONResponse({"error":str(e)}, status_code=500)

@app.get("/api/v34/moneyflow")
def api_moneyflow():
    try:
        with LOCK:
            mf=STATE.get("money_flow",{})
            inflow=mf.get("avg_vol_change",0)
            inflow_val=200 if inflow<0 else 300+inflow*10
            outflow=abs(inflow)*1.5 if inflow<0 else inflow*0.6
            return JSONResponse(json_safe({
                "inflow":inflow_val,"outflow":outflow,"net_flow":inflow_val-outflow,
                "details":mf,
                "verdict":"GUT" if mf.get("avg_vol_change",0)<-10 else "VORSICHT" if mf.get("avg_vol_change",0)>20 else "NEUTRAL",
                "indices": STATE.get("hubble_indices",{})
            }))
    except Exception as e:
        log.error(f"[api_moneyflow] {e}")
        return JSONResponse({"inflow":0,"outflow":0,"error":str(e)})

@app.get("/api/v34/active")
def api_active():
    try:
        with LOCK:
            return JSONResponse(json_safe({"active_calls":STATE.get("open_positions",[]),"closed_today":STATE.get("closed_today",[])[-5:],"equity":STATE.get("equity",0)}))
    except Exception as e:
        log.error(f"[api_active] {e}")
        return JSONResponse({"active_calls":[],"error":str(e)})

@app.post("/api/v34/wizdraw/close/{call_id}")
def api_wizdraw_close(call_id:str):
    try:
        with LOCK:
            res=wizdraw_manual_close(call_id,STATE)
            log.info(f"[WIZDRAW] close {call_id} {res}")
            return JSONResponse(json_safe(res))
    except Exception as e:
        log.error(f"[wizdraw_close] {call_id} {e} {traceback.format_exc()}")
        return JSONResponse({"error":str(e)}, status_code=500)

@app.get("/api/v34/paper")
def api_paper():
    try:
        with LOCK:
            trades=STATE.get("closed_today",[]); dist=paper_executor.evaluate_paper_distribution(trades)
            return JSONResponse(json_safe({"budget":paper_executor.budget,"current_equity":STATE.get("equity",0),"open_positions":STATE.get("open_positions",[]),"closed_today":trades[-20:],"distribution":dist,"config":paper_executor.config,"logs":paper_executor.logs[-50:]}))
    except Exception as e:
        log.error(f"[api_paper] {e}")
        return JSONResponse({"error":str(e)})

@app.get("/api/v34/universe")
def api_universe():
    return JSONResponse({"universe":UNIVERSE_100,"count":len(UNIVERSE_100)})

@app.get("/api/relax/status")
def api_status():
    try:
        with LOCK:
            update_status()
            return JSONResponse(json_safe(STATE))
    except Exception as e:
        return JSONResponse({"error":str(e)})

@app.get("/api/relax/scan")
def api_scan():
    try:
        with LOCK:
            res=scan_all()
            return JSONResponse(json_safe(res))
    except Exception as e:
        return JSONResponse(json_safe({"status":"ERROR","reason":str(e)}))

@app.get("/relax", response_class=HTMLResponse)
def relax_dashboard():
    try:
        with LOCK:
            update_status()
            s=json_safe(STATE.copy())
        status_color={"JAGT":"#00e676","PAUSE":"#ffea00","FEIERABEND_GEWINN":"#00b0ff","FEIERABEND_SCHUTZ":"#ff1744"}.get(s.get('status'),"#888")
        return HTMLResponse(f"<html><body style='background:#070707;color:#eee;font-family:monospace;padding:16px'><h1>RELAX {s.get('status')} <span style='background:{status_color};color:#000;padding:4px 12px;border-radius:20px'>{s.get('status')}</span> <a href='/dashboard' style='color:#39ff14'>-> V3.4.5 HUBBLE</a></h1><div>{s.get('status_reason')} | Equity ${s.get('equity',0.0):.2f} | Hubble {len(s.get('hubble_scores',[]))} Ready {len([h for h in s.get('hubble_scores',[]) if h.get('ready')])}</div></body></html>")
    except Exception as e:
        return HTMLResponse(f"<html><body>Error {e}</body></html>")

# === SCHEDULER - DICHT - 34 JAHRE FLUGFÄHIG ===
scheduler=BackgroundScheduler()
scheduler.add_job(lambda: [update_status(), paper_monitor_positions(), monitor_positions(get_market_data, STATE)], 'interval', seconds=30, id='clan_monitor', max_instances=1, coalesce=True)
scheduler.add_job(run_turtle_scan, 'interval', seconds=120, id='turtle_2m', max_instances=1, coalesce=True, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")))
scheduler.add_job(run_splinter_inspection, 'interval', minutes=5, id='splinter_5m', max_instances=1, coalesce=True)
scheduler.add_job(run_hubble_inspection, 'interval', minutes=5, id='hubble_5m', max_instances=1, coalesce=True)
scheduler.add_job(hubble_engine.fetch_indices, 'interval', minutes=15, id='indices_15m', max_instances=1, coalesce=True)
scheduler.start()
update_status()
hubble_engine.fetch_indices()
log.info("V3.4.5 HUBBLE DICHT gestartet - 2MIN TURTLE + 5MIN HUBBLE + 15MIN INDICES - NO AUTO TRADING - LAFETTE GESICHERT")
print("V3.4.5 HUBBLE DICHT gestartet - 2MIN TURTLE + 5MIN HUBBLE + 15MIN INDICES - /api/v34/hubble + /api/v34/debug + /api/v34/health für UptimeRobot")
