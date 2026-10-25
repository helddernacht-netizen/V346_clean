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
from datetime import datetime
from zoneinfo import ZoneInfo
from threading import Lock, Thread
from apscheduler.schedulers.background import BackgroundScheduler
BOOT_TIME = datetime.now(ZoneInfo("Europe/Berlin"))
log.info(f"[BOOT] V3.4.6 FIXED BOOT={BOOT_TIME.isoformat()}")
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
        def should_auto_sell(self,pos):
            return False,"HOLD",{}
        def evaluate_paper_distribution(self,trades):
            return {}
app=FastAPI(title="TURTLE V3.4.6 FIXED CLEAN NO-BREAKER", version="3.4.6-clean")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
MAX_TRADES_PER_DAY=2
COOLDOWN_AFTER_TRADE_MIN=30
COOLDOWN_AFTER_LOSS_MIN=120
DAILY_PROFIT_TARGET_PCT=8.0
DAILY_LOSS_LIMIT_PCT=-4.0
STATE=load_state()
if "hubble_scores" not in STATE:
    STATE["hubble_scores"]=[]
if "hubble_indices" not in STATE:
    STATE["hubble_indices"]={"btc_dom":52.5,"usdt_dom":5.2,"fractal":"INIT"}
HUBBLE_CFG={"ath_dd_min":-70,"ath_dd_max":-40,"vol_dryup_pct":0.4,"rsi_oversold":38,"hubble_min_score":75,"cache_minutes":15}
LOCK=Lock()

def is_blacklist_time():
    return False,""
def is_best_time():
    return True

def load_universe_100_fixed():
    # KEIN API Call beim Boot -> kein 429, schneller Start
    base = ["BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","LINKUSDT","ARBUSDT","WIFUSDT","PEPEUSDT","BONKUSDT","FLOKIUSDT","DOGEUSDT","SHIBUSDT","MATICUSDT","DOTUSDT","ADAUSDT","NEARUSDT","RNDRUSDT","FETUSDT","INJUSDT","SEIUSDT"]
    return base * 5

UNIVERSE_100=load_universe_100_fixed()
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
    except:
        return str(obj)

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
    except Exception as e:
        log.error(str(e))

def update_status():
    global STATE
    try:
        check_daily_reset()
        STATE["status"]="JAGT"
        STATE["status_reason"]="Clean ohne Breaker - jagt dauerhaft"
    except:
        STATE["status"]="JAGT"

def paper_monitor_positions():
    pass

class HubbleEngine:
    def __init__(self):
        self.indices_cache={"btc_dom":52.5,"usdt_dom":5.2,"fractal":"INIT"}
        self.last_fetch=None
    def fetch_indices(self):
        try:
            r=requests.get("https://api.coingecko.com/api/v3/global", timeout=12)
            j=r.json()
            mcap=j.get("data",{}).get("market_cap_percentage",{})
            btc=float(mcap.get("btc",52.5))
            usdt=float(mcap.get("usdt",5.2))
            self.indices_cache={"btc_dom":round(btc,2),"usdt_dom":round(usdt,2),"last_update":datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),"fractal":"NEUTRAL"}
            self.last_fetch=datetime.now()
            with LOCK:
                STATE["hubble_indices"]=self.indices_cache.copy()
                save_state(STATE)
            return self.indices_cache
        except Exception as e:
            return self.indices_cache
    def calc_hubble_score(self, symbol, item, ohlc_24h, ohlc_30d, ohlc_180d, atr, bb_width, rsi, mf_signal):
        try:
            curr_price=float(item.get("price",0) or 0)
            ath_dd=float(item.get("ath_dd",-20))
            rsi=float(rsi) if rsi is not None else 50.0
            bb_width=float(bb_width) if bb_width is not None else 0.5
            btc_dom=float(self.indices_cache.get("btc_dom",52.5))
            score=0
            if -70 <= ath_dd <= -40:
                score+=30
            elif -40 < ath_dd <= -25:
                score+=15
            if rsi<38:
                score+=20
            elif rsi<45:
                score+=10
            if bb_width<0.4:
                score+=20
            elif bb_width<0.6:
                score+=10
            if btc_dom<52:
                score+=15
            if mf_signal and mf_signal.get("verdict")=="BULL":
                score+=5
            score=max(0,min(100,score))
            ready=score>=75
            timewindow=datetime.now(ZoneInfo("Europe/Berlin")).strftime("%H:%M")
            return json_safe({"symbol":symbol,"score":int(score),"ready":bool(ready),"ath_dd":ath_dd,"rsi":round(rsi,1),"bb_width":round(bb_width,3),"btc_dom":btc_dom,"price":curr_price,"timewindow":timewindow,"timestamp":datetime.now(ZoneInfo("Europe/Berlin")).isoformat()})
        except Exception as e:
            return {"symbol":symbol,"score":0,"ready":False,"timewindow":datetime.now(ZoneInfo("Europe/Berlin")).strftime("%H:%M")}

hubble_engine=HubbleEngine()

def run_turtle_scan():
    global STATE
    try:
        with LOCK:
            update_status()
            results=turtle_scanner.scan_once(get_market_data)
            STATE["vorauswahl_queue"]=results[:20]
            STATE["dynamic_whitelist"]=[r["symbol"] if isinstance(r, dict) else r for r in results[:20]]
            save_state(STATE)
            log.info(f"[TURTLE] queue {len(results)}")
            return results
    except Exception as e:
        log.error(f"[TURTLE] {e} {traceback.format_exc()}")
        return []

def run_splinter_inspection():
    global STATE
    try:
        with LOCK:
            queue=STATE.get("vorauswahl_queue",[])[:8]
            inspection_results=[]
            for item in queue:
                try:
                    sym=item["symbol"] if isinstance(item, dict) else item
                    data=get_market_data(sym)
                    if data.get("price",0)==0:
                        continue
                    ok,checks,meta=check_filters(sym, data, [])
                    inspection_results.append(json_safe({"symbol":sym,"ok":bool(ok),"price":float(data.get("price",0))}))
                except:
                    continue
                time.sleep(0.3)
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
            queue=STATE.get("vorauswahl_queue",[])[:8]
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
                    except:
                        pass
                    item_dict=item if isinstance(item, dict) else {"symbol":sym,"price":data.get("price",0),"ath_dd":-30}
                    score_dict=hubble_engine.calc_hubble_score(sym, item_dict, ohlc_24h, ohlc_30d, ohlc_180d, atr, bb_width, rsi, {"verdict":"NEUTRAL"})
                    hubble_results.append(score_dict)
                except:
                    continue
                time.sleep(0.4)
            STATE["hubble_scores"]=sorted(hubble_results, key=lambda x: x.get("score",0), reverse=True)
            STATE["hubble_indices"]=indices
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
    return {"status":"ok","version":"3.4.6-clean-no-breaker","mode":"JAGT","kraken_auth": getattr(connector, "kraken_auth", False),"uptime":int((datetime.now(ZoneInfo("Europe/Berlin"))-BOOT_TIME).total_seconds())}

@app.get("/", response_class=HTMLResponse)
def root_dashboard():
    try:
        for tmpl in ["templates/dashboard_v34_hubble.html", "templates/dashboard_v34.html", "templates/dashboard_v34_clean.html"]:
            tmpl_path = os.path.join(os.path.dirname(__file__), tmpl)
            if os.path.exists(tmpl_path):
                with open(tmpl_path, "r", encoding="utf-8") as f:
                    return HTMLResponse(f.read())
    except Exception as e:
        log.error(f"[DASHBOARD] fail {e}")
    try:
        with LOCK:
            equity = STATE.get("equity",0)
            cnt = len(STATE.get("hubble_scores",[]))
            ready = len([h for h in STATE.get("hubble_scores",[]) if h.get("ready")])
            status = STATE.get("status","JAGT")
        return HTMLResponse(f"<html><body style='background:#070707;color:#eee;font-family:monospace;padding:20px'><h1>TURTLE V3.4.6 CLEAN NO-BREAKER {status}</h1><p>Equity ${equity:.2f} | Hubble {cnt} Ready {ready}</p><p><a href='/api/v34/health'>health</a> | <a href='/api/v34/hubble'>hubble</a> | <a href='/api/v34/rina'>rina</a></p></body></html>")
    except Exception as e:
        return HTMLResponse(f"<html><body>Error {e}</body></html>")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_alias():
    return root_dashboard()

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
                "version":"RINA RAKETE CLEAN NO-BREAKER",
                "available":RINA_AVAILABLE,
                "freedom_window":"5min",
                "top_ready":ready,
                "scores":top,
                "active_freedom_windows":freedom_windows,
                "hochsitz_anker":STATE.get("hochsitz",[]),
                "status":"online"
            }))
    except Exception as e:
        return JSONResponse({"error":str(e),"top_ready":[],"scores":[],"active_freedom_windows":[]}, status_code=200)

@app.get("/api/v34/turtles")
def api_turtles():
    with LOCK:
        return JSONResponse(json_safe({"queue":STATE.get("vorauswahl_queue",[])}))
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
        return JSONResponse(json_safe({"scores":sorted(scores, key=lambda x: x.get("score",0), reverse=True),"top_ready":[s for s in scores if s.get("ready")],"indices":STATE.get("hubble_indices",{})}))
@app.get("/api/v34/debug")
def api_debug():
    with LOCK:
        return JSONResponse(json_safe({"boot":BOOT_TIME.isoformat(),"uptime_sec":int((datetime.now(ZoneInfo("Europe/Berlin"))-BOOT_TIME).total_seconds()),"status":STATE.get("status"),"hubble_cnt":len(STATE.get("hubble_scores",[])),"queue_cnt":len(STATE.get("vorauswahl_queue",[]))}))
@app.get("/api/v34/moneyflow")
def api_moneyflow():
    with LOCK:
        return JSONResponse(json_safe({"indices":STATE.get("hubble_indices",{})}))
@app.get("/api/v34/active")
def api_active():
    with LOCK:
        return JSONResponse(json_safe({"active_calls":STATE.get("open_positions",[])}))

scheduler=BackgroundScheduler(timezone=ZoneInfo("Europe/Berlin"), job_defaults={'misfire_grace_time': 900, 'coalesce': True, 'max_instances': 1})
scheduler.add_job(lambda: [update_status(), paper_monitor_positions(), monitor_positions(get_market_data, STATE)], 'interval', seconds=30, id='clan_monitor', coalesce=True, misfire_grace_time=300)
scheduler.add_job(run_turtle_scan, 'interval', minutes=2, id='turtle_2m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")))
scheduler.add_job(run_splinter_inspection, 'interval', minutes=5, id='splinter_5m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")) + __import__('datetime').timedelta(seconds=30))
scheduler.add_job(run_hubble_inspection, 'interval', minutes=5, id='hubble_5m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")) + __import__('datetime').timedelta(seconds=60))
scheduler.add_job(hubble_engine.fetch_indices, 'interval', minutes=15, id='indices_15m', coalesce=True, misfire_grace_time=900)
scheduler.add_job(run_turtle_scan, 'interval', minutes=2, id='turtle_2m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")))
scheduler.add_job(run_splinter_inspection, 'interval', minutes=5, id='splinter_5m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")) + __import__('datetime').timedelta(seconds=30))
scheduler.add_job(run_hubble_inspection, 'interval', minutes=5, id='hubble_5m', coalesce=True, misfire_grace_time=900, next_run_time=datetime.now(ZoneInfo("Europe/Berlin")) + __import__('datetime').timedelta(seconds=60))
scheduler.add_job(hubble_engine.fetch_indices, 'interval', minutes=15, id='indices_15m', coalesce=True, misfire_grace_time=900)
scheduler.start()

def _boot_warmup():
    time.sleep(3)
    try:
        run_turtle_scan()
        time.sleep(2)
        run_hubble_inspection()
        log.info("[BOOT] warmup done")
    except Exception as e:
        log.error(f"[BOOT] warmup fail {e}")

Thread(target=_boot_warmup, daemon=True).start()
update_status()
hubble_engine.fetch_indices()
log.info("V3.4.6 CLEAN NO-BREAKER gestartet")
