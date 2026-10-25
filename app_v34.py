import sys, os
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
import logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s][%(levelname)s][%(name)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
log = logging.getLogger("HUBBLE")
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Tuple
import traceback, json, numpy as np, time, requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from threading import Lock, Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from apscheduler.schedulers.background import BackgroundScheduler

BOOT_TIME = datetime.now(ZoneInfo("Europe/Berlin"))
log.info(f"[BOOT] V3.4.7 CLEAN 100 + MEMORY BOOT={BOOT_TIME.isoformat()}")

try:
    from core.donatello.persistent_state import load_state, save_state, log_day, DEFAULT_STATE
    from core.leonardo.reasoning import get_market_data, check_filters, STABLECOIN_BLACKLIST, get_ohlc_three_windows, calc_atr, calc_bollinger_width, calc_rsi
    from core.raphael.execution import open_position, monitor_positions, wizdraw_manual_close, close_position
    from core.splinter.turtle_scanner import TurtleScanner
    from core.splinter.cell import SplinterCell
    from core.moneyflow.scanner import MoneyFlowScanner
    from core.exchanges.connector import connector
    log.info(f"[BOOT] core OK {list(connector.exchanges.keys())}")
except Exception as e:
    log.error(f"[BOOT] core fail {e}")
    raise

RINA_AVAILABLE=False
try:
    from core.rina_rakete.freedom_recall import RinaRaketeEngine
    from core.rina_rakete.hochsitz import HochsitzAnchor
    RINA_AVAILABLE=True
except Exception as e:
    RINA_AVAILABLE=False
    class RinaRaketeEngine:
        def __init__(self, freedom_window_min=5):
            self.freedom_window_min=freedom_window_min
        def get_status(self):
            return {"version":"FALLBACK"}

try:
    from paper_trading_execution_V3_4 import PaperTradingExecutionV34
except Exception as e:
    class PaperTradingExecutionV34:
        def __init__(self):
            self.budget=100000
            self.config={"max_exposure_usd":30000, "hubble_min_score":75}
            self.logs=[]
        def should_auto_sell(self,pos): return False,"HOLD",{}
        def evaluate_paper_distribution(self,trades): return {}

app=FastAPI(title="TURTLE V3.4.7 CLEAN 100 MEMORY", version="3.4.7-clean")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATE=load_state()
if "hubble_scores" not in STATE: STATE["hubble_scores"]=[]
if "hubble_indices" not in STATE: STATE["hubble_indices"]={"btc_dom":52.5,"usdt_dom":5.2,"fractal":"INIT"}
if "hubble_history" not in STATE: STATE["hubble_history"]=[]
if "turtle_history" not in STATE: STATE["turtle_history"]=[]
if "rsi_history" not in STATE: STATE["rsi_history"]={}
if "ath_memory" not in STATE: STATE["ath_memory"]={}
if "vorauswahl_queue" not in STATE: STATE["vorauswahl_queue"]=[]

LOCK=Lock()

def is_blacklist_time(): return False,""
def is_best_time(): return True

def load_universe_100_fixed():
    return [
        "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","LINKUSDT","ARBUSDT","WIFUSDT","PEPEUSDT","BONKUSDT","FLOKIUSDT",
        "DOGEUSDT","SHIBUSDT","MATICUSDT","DOTUSDT","ADAUSDT","NEARUSDT","RNDRUSDT","FETUSDT","INJUSDT","SEIUSDT",
        "SUIUSDT","APTUSDT","OPUSDT","ENAUSDT","JUPUSDT","PYTHUSDT","TIAUSDT","STRKUSDT","ZKUSDT","WUSDT",
        "ONDOUSDT","RENDERUSDT","TAOUSDT","AKTUSDT","ARUSDT","FILUSDT","ATOMUSDT","LDOUSDT","ETCUSDT","XRPUSDT",
        "LTCUSDT","BCHUSDT","UNIUSDT","AAVEUSDT","MKRUSDT","SNXUSDT","CRVUSDT","COMPUSDT","ENSUSDT","GRTUSDT",
        "AGIXUSDT","OCEANUSDT","ORDIUSDT","BLURUSDT","DYDXUSDT","GMXUSDT","RDNTUSDT","STGUSDT","MAGICUSDT","WLDUSDT",
        "KASUSDT","CFXUSDT","AGLDUSDT","IMXUSDT","FLOWUSDT","CHZUSDT","GALAUSDT","SANDUSDT","MANAUSDT","APEUSDT",
        "AXSUSDT","GMTUSDT","SSVUSDT","FXSUSDT","BALUSDT","1INCHUSDT","ZRXUSDT","BATUSDT","ENJUSDT","THETAUSDT",
        "FTMUSDT","ALGOUSDT","HBARUSDT","VETUSDT","TRXUSDT","EOSUSDT","XTZUSDT","EGLDUSDT","KAVAUSDT","ROSEUSDT",
        "ONEUSDT","CELOUSDT","IOSTUSDT","ZILUSDT","QTUMUSDT","WAVESUSDT","ICXUSDT","ONTUSDT","KLAYUSDT","APTUSDT"
    ][:100]

UNIVERSE_100=load_universe_100_fixed()
SCAN_CURSOR=0
SCAN_LOCK=False  # verhindert Doppel-Scan
turtle_scanner=TurtleScanner(UNIVERSE_100)
splinter_cell=SplinterCell()
moneyflow_scanner=MoneyFlowScanner()
paper_executor=PaperTradingExecutionV34()

def json_safe(obj):
    try:
        if isinstance(obj,(np.bool_,bool)): return bool(obj)
        if isinstance(obj,(np.integer,)): return int(obj)
        if isinstance(obj,(np.floating,)): return float(obj)
        if isinstance(obj,np.ndarray): return obj.tolist()
        if isinstance(obj,dict): return {k:json_safe(v) for k,v in obj.items()}
        if isinstance(obj,(list,tuple)): return [json_safe(x) for x in obj]
        if hasattr(obj,'__dict__'): return json_safe(obj.__dict__)
        return obj
    except: return str(obj)

class PoolPayload(BaseModel):
    pool: List[str]
    details: Optional[List[dict]]=None

def check_daily_reset():
    global STATE
    try:
        today=datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat()
        if STATE.get("last_reset_date")!=today:
            STATE["initial_equity_today"]=STATE.get("equity",0)
            STATE["daily_pnl_pct"]=0
            STATE["trades_today"]=0
            STATE["closed_today"]=[]
            STATE["status"]="JAGT"
            STATE["last_reset_date"]=today
            save_state(STATE)
    except Exception as e: log.error(str(e))

def update_status():
    global STATE
    try:
        check_daily_reset()
        STATE["status"]="JAGT"
        STATE["status_reason"]="V3.4.7 CLEAN 100 + MEMORY rotierend"
    except: STATE["status"]="JAGT"

def paper_monitor_positions(): pass

class HubbleEngine:
    def __init__(self):
        self.indices_cache={"btc_dom":52.5,"usdt_dom":5.2,"fractal":"INIT"}
    def fetch_indices(self):
        try:
            r=requests.get("https://api.coingecko.com/api/v3/global", timeout=12)
            j=r.json()
            mcap=j.get("data",{}).get("market_cap_percentage",{})
            btc=float(mcap.get("btc",52.5))
            usdt=float(mcap.get("usdt",5.2))
            self.indices_cache={"btc_dom":round(btc,2),"usdt_dom":round(usdt,2),"last_update":datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),"fractal":"NEUTRAL"}
            with LOCK:
                STATE["hubble_indices"]=self.indices_cache.copy()
                save_state(STATE)
            return self.indices_cache
        except: return self.indices_cache
    def calc_hubble_score(self, symbol, item, ohlc_24h, ohlc_30d, ohlc_180d, atr, bb_width, rsi, mf_signal):
        try:
            curr_price=float(item.get("price",0) or 0)
            ath_dd=float(item.get("ath_dd",-20))
            rsi_val=float(rsi) if rsi is not None else 50.0
            bb_width=float(bb_width) if bb_width is not None else 0.5
            btc_dom=float(self.indices_cache.get("btc_dom",52.5))
            mem_bonus=5 if symbol in STATE.get("ath_memory",{}) and STATE["ath_memory"][symbol].get("was_ready") else 0
            score=0
            if -70 <= ath_dd <= -40: score+=30
            elif -40 < ath_dd <= -25: score+=15
            if rsi_val<38: score+=20
            elif rsi_val<45: score+=10
            if bb_width<0.4: score+=20
            elif bb_width<0.6: score+=10
            if btc_dom<52: score+=15
            if mf_signal and mf_signal.get("verdict")=="BULL": score+=5
            score+=mem_bonus
            score=max(0,min(100,score))
            ready=score>=75
            timewindow=datetime.now(ZoneInfo("Europe/Berlin")).strftime("%H:%M")
            return json_safe({"symbol":symbol,"score":int(score),"ready":bool(ready),"ath_dd":ath_dd,"rsi":round(rsi_val,1),"bb_width":round(bb_width,3),"btc_dom":btc_dom,"price":curr_price,"timewindow":timewindow,"timestamp":datetime.now(ZoneInfo("Europe/Berlin")).isoformat()})
        except: return {"symbol":symbol,"score":0,"ready":False,"timewindow":datetime.now(ZoneInfo("Europe/Berlin")).strftime("%H:%M")}

hubble_engine=HubbleEngine()

def safe_get(sym):
    try:
        d=get_market_data(sym)
        if d and d.get("price",0)>0:
            return {"symbol":sym,"price":float(d.get("price",0)),"ath_dd":float(d.get("ath_dd",-30)),"ok":True, "raw":d}
    except Exception as e: log.error(f"[SAFE_GET] {sym} {e}")
    return {"symbol":sym,"price":0,"ath_dd":-30,"ok":False}
def safe_get(sym):
    try:
        d=get_market_data(sym)
        if d and float(d.get("price",0) or 0)>0:
            return {"symbol":sym,"price":float(d.get("price",0)),"ath_dd":float(d.get("ath_dd",-30)),"ok":True}
    except Exception as e:
        log.error(f"[SAFE_GET] {sym} {e}")
    return {"symbol":sym,"price":0,"ath_dd":-30,"ok":False}

def run_turtle_scan():
    global STATE, SCAN_CURSOR, SCAN_LOCK
    if SCAN_LOCK:
        log.info("[TURTLE] SKIP already scanning")
        return STATE.get("vorauswahl_queue",[])
    SCAN_LOCK=True
    try:
        with LOCK:
            batch=UNIVERSE_100[SCAN_CURSOR:SCAN_CURSOR+20]
            SCAN_CURSOR=(SCAN_CURSOR+20) % 100
            log.info(f"[TURTLE] SCAN cursor {SCAN_CURSOR} batch {batch[0]}..{batch[-1]} len={len(batch)}")
        results=[]
        # SEQUENZIELL statt 10 Threads = 80% weniger RAM
        for sym in batch:
            try:
                r=safe_get(sym)
                if r["ok"]:
                    results.append(r)
                    log.info(f"[TURTLE] + {sym} price {r['price']}")
                time.sleep(0.6)  # 0.6 Sek Pause = kein Rate Limit, wenig RAM
            except Exception as e:
                log.error(f"[TURTLE] {sym} err {e}")
                continue
        with LOCK:
            old=STATE.get("vorauswahl_queue",[])
            merged={r["symbol"]: r for r in old}
            for r in results: merged[r["symbol"]]=r
            for r in results:
                STATE["ath_memory"][r["symbol"]]={"last_seen":datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),"ath_dd":r["ath_dd"]}
            STATE["vorauswahl_queue"]=list(merged.values())[:100]
            STATE["dynamic_whitelist"]=list(merged.keys())[:20]
            STATE["turtle_history"].append({"ts":datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),"batch":batch,"found":len(results)})
            STATE["turtle_history"]=STATE["turtle_history"][-30:]  # nur 30 statt 100 = RAM sparen
            save_state(STATE)
            log.info(f"[TURTLE] DONE batch {len(results)}/20 total {len(STATE['vorauswahl_queue'])} mem OK")
            return STATE["vorauswahl_queue"]
    except Exception as e:
        log.error(f"[TURTLE] FATAL {e} {traceback.format_exc()}")
        return []
    finally:
        SCAN_LOCK=False
def run_splinter_inspection():
    global STATE
    try:
        with LOCK:
            queue=STATE.get("vorauswahl_queue",[])[:8]
            if not queue: return []
        inspection_results=[]
        for item in queue:
            try:
                sym=item["symbol"] if isinstance(item, dict) else item
                data=get_market_data(sym)
                if data.get("price",0)==0: continue
                ok,checks,meta=check_filters(sym, data, [])
                inspection_results.append(json_safe({"symbol":sym,"ok":bool(ok),"price":float(data.get("price",0))}))
            except: continue
            time.sleep(0.3)
        with LOCK:
            STATE["splinter_inspection"]=inspection_results
            save_state(STATE)
        return inspection_results
    except Exception as e:
        log.error(f"[SPLINTER] {e}")
        return []

def run_hubble_inspection():
    global STATE
    try:
        with LOCK:
            queue=STATE.get("vorauswahl_queue",[])[:12]
            if not queue:
                queue=[{"symbol":s,"price":0,"ath_dd":-35} for s in UNIVERSE_100[:8]]
        indices=hubble_engine.fetch_indices()
        hubble_results=[]
        for item in queue:
            try:
                sym=item["symbol"] if isinstance(item, dict) else item
                data=get_market_data(sym)
                ohlc_24h, ohlc_30d, ohlc_180d=None,None,None
                atr,bb_width,rsi=None,None,None
                try:
                    ohlc_24h, ohlc_30d, ohlc_180d=get_ohlc_three_windows(sym)
                    if ohlc_24h:
                        closes=ohlc_24h.get('close',[])
                        if len(closes)>0:
                            atr=calc_atr(ohlc_24h) if 'high' in ohlc_24h else None
                            bb_width=calc_bollinger_width(ohlc_24h)
                            rsi=calc_rsi(closes)
                except: pass
                item_dict=item if isinstance(item, dict) else {"symbol":sym,"price":data.get("price",0),"ath_dd":-30}
                score_dict=hubble_engine.calc_hubble_score(sym, item_dict, ohlc_24h, ohlc_30d, ohlc_180d, atr, bb_width, rsi, {"verdict":"NEUTRAL"})
                hubble_results.append(score_dict)
                with LOCK:
                    if sym not in STATE["rsi_history"]: STATE["rsi_history"][sym]=[]
                    STATE["rsi_history"][sym].append(rsi)
                    STATE["rsi_history"][sym]=STATE["rsi_history"][sym][-15:]
                    if score_dict.get("ready"):
                        STATE["ath_memory"][sym]={"was_ready":True,"score":score_dict.get("score"),"ts":score_dict.get("timestamp")}
            except: continue
            time.sleep(0.4)
        with LOCK:
            STATE["hubble_scores"]=sorted(hubble_results, key=lambda x: x.get("score",0), reverse=True)
            STATE["hubble_indices"]=indices
            STATE["hubble_history"].append({"ts":datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),"scores":STATE["hubble_scores"][:10]})
            STATE["hubble_history"]=STATE["hubble_history"][-50:]
            save_state(STATE)
            log.info(f"[HUBBLE] scores {len(hubble_results)} ready {len([h for h in hubble_results if h.get('ready')])}")
            return STATE["hubble_scores"]
    except Exception as e:
        log.error(f"[HUBBLE] {e} {traceback.format_exc()}")
        return []

@app.get("/health")
@app.head("/health")
@app.get("/api/v34/health")
@app.get("/ping")
async def health():
    return {"status":"ok","version":"3.4.7-clean-100-memory","mode":"JAGT","kraken_auth": getattr(connector, "kraken_auth", False),"uptime":int((datetime.now(ZoneInfo("Europe/Berlin"))-BOOT_TIME).total_seconds()),"queue":len(STATE.get("vorauswahl_queue",[]))}

@app.get("/", response_class=HTMLResponse)
def root_dashboard():
    try:
        for tmpl in ["templates/dashboard_v34_hubble.html", "templates/dashboard_v34.html", "templates/dashboard_v34_clean.html"]:
            tmpl_path = os.path.join(os.path.dirname(__file__), tmpl)
            if os.path.exists(tmpl_path):
                with open(tmpl_path, "r", encoding="utf-8") as f:
                    return HTMLResponse(f.read())
    except Exception as e: log.error(f"[DASHBOARD] fail {e}")
    try:
        with LOCK:
            equity = STATE.get("equity",0)
            cnt = len(STATE.get("hubble_scores",[]))
            ready = len([h for h in STATE.get("hubble_scores",[]) if h.get("ready")])
            status = STATE.get("status","JAGT")
        return HTMLResponse(f"<html><body style='background:#070707;color:#eee;font-family:monospace;padding:20px'><h1>TURTLE V3.4.7 100 MEMORY {status}</h1><p>Equity ${equity:.2f} | Hubble {cnt} Ready {ready} | Queue {len(STATE.get('vorauswahl_queue',[]))}</p><p><a href='/api/v34/health'>health</a> | <a href='/api/v34/hubble'>hubble</a> | <a href='/api/v34/rina'>rina</a> | <a href='/api/v34/debug'>debug</a></p></body></html>")
    except Exception as e:
        return HTMLResponse(f"<html><body>Error {e}</body></html>")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_alias(): return root_dashboard()

@app.get("/api/v34/rina")
@app.get("/api/v34/rina/freedom")
def api_rina():
    try:
        with LOCK:
            scores=STATE.get("hubble_scores",[])
            top=sorted(scores, key=lambda x: x.get("score",0), reverse=True)[:12]
            ready=[s for s in top if s.get("ready")]
            freedom_windows=[{"symbol":r["symbol"],"start":r.get("timewindow"),"score":r.get("score"),"status":"ACTIVE"} for r in ready[:3]]
            return JSONResponse(json_safe({
                "version":"RINA RAKETE V3.4.7 MEMORY",
                "available":RINA_AVAILABLE,
                "freedom_window":"5min",
                "top_ready":ready,
                "scores":top,
                "active_freedom_windows":freedom_windows,
                "hochsitz_anker":STATE.get("hochsitz",[]),
                "memory":{"hubble_history_len":len(STATE.get("hubble_history",[])),"turtle_history_len":len(STATE.get("turtle_history",[])),"ath_memory":len(STATE.get("ath_memory",{}))},
                "status":"online"
            }))
    except Exception as e:
        return JSONResponse({"error":str(e),"top_ready":[],"scores":[],"active_freedom_windows":[]}, status_code=200)

@app.get("/api/v34/turtles")
def api_turtles():
    with LOCK:
        return JSONResponse(json_safe({"queue":STATE.get("vorauswahl_queue",[]),"cursor":SCAN_CURSOR,"universe":len(UNIVERSE_100)}))
@app.get("/api/v34/splinter")
def api_splinter():
    with LOCK:
        return JSONResponse(json_safe({"inspection":STATE.get("splinter_inspection",[])}))
@app.get("/api/v34/hubble")
def api_hubble():
    with LOCK:
        scores=STATE.get("hubble_scores",[])
        if not scores:
            scores=[{"symbol":"BTCUSDT","score":65,"ready":False,"ath_dd":-35,"rsi":42,"timewindow":datetime.now(ZoneInfo("Europe/Berlin")).strftime("%H:%M")}]
        return JSONResponse(json_safe({"scores":sorted(scores, key=lambda x: x.get("score",0), reverse=True),"top_ready":[s for s in scores if s.get("ready")],"indices":STATE.get("hubble_indices",{}),"history_len":len(STATE.get("hubble_history",[]))}))
@app.get("/api/v34/debug")
def api_debug():
    with LOCK:
        return JSONResponse(json_safe({
            "boot":BOOT_TIME.isoformat(),
            "uptime_sec":int((datetime.now(timezone.utc) - BOOT_TIME).total_seconds()),
            "status":STATE.get("status"),
            "hubble_cnt":len(STATE.get("hubble_scores",[])),
            "queue_cnt":len(STATE.get("vorauswahl_queue",[])),
            "cursor":SCAN_CURSOR,
            "memory":{
                "hubble_history":len(STATE.get("hubble_history",[])),
                "turtle_history":len(STATE.get("turtle_history",[])),
                "ath_memory":len(STATE.get("ath_memory",{})),
                "rsi_history":len(STATE.get("rsi_history",{}))
            },
            "status_live":"V347_CLEAN_100_MEMORY LIVE"
        }))
@app.get("/api/v34/moneyflow")
def api_moneyflow():
    with LOCK:
        return JSONResponse(json_safe({"indices":STATE.get("hubble_indices",{})}))

scheduler=BackgroundScheduler(timezone=ZoneInfo("Europe/Berlin"), job_defaults={'misfire_grace_time': 900, 'coalesce': True, 'max_instances': 1})
try: scheduler.remove_all_jobs()
except: pass
scheduler.add_job(lambda: [update_status(), paper_monitor_positions(), monitor_positions(get_market_data, STATE)], 'interval', seconds=30, id='clan_monitor', coalesce=True, misfire_grace_time=300, replace_existing=True)
scheduler.add_job(run_turtle_scan, 'interval', minutes=2, id='turtle_2m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")), replace_existing=True)
scheduler.add_job(run_splinter_inspection, 'interval', minutes=5, id='splinter_5m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")) + __import__('datetime').timedelta(seconds=30), replace_existing=True)
scheduler.add_job(run_hubble_inspection, 'interval', minutes=5, id='hubble_5m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")) + __import__('datetime').timedelta(seconds=60), replace_existing=True)
scheduler.add_job(hubble_engine.fetch_indices, 'interval', minutes=15, id='indices_15m', coalesce=True, misfire_grace_time=900, replace_existing=True)
scheduler.start()

def _boot_warmup():
    time.sleep(8)  # erst 8 Sek warten bis Uvicorn steht
    try:
        log.info("[BOOT] warmup start")
        run_turtle_scan()  # nur EIN Scan
        time.sleep(3)
        run_hubble_inspection()
        log.info("[BOOT] warmup done - queue + hubble gefüllt + memory aktiv")
    except Exception as e:
        log.error(f"[BOOT] warmup fail {e} {traceback.format_exc()}")

Thread(target=_boot_warmup, daemon=True).start()
