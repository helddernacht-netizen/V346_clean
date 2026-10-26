import os, time, json, math, traceback, asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from threading import Lock
from fastapi import FastAPI
from fastapi.responses import JSONResponse, HTMLResponse

try:
    from hubble_engine import HubbleEngine
    from rina_engine import RinaEngine
    from market_data import get_market_data, get_ohlc_three_windows, calc_atr, calc_bollinger_width, calc_rsi
    from connector import ExchangeConnector
    import paper_trading_execution_V3_4 as paper_executor
    CORE_OK = True
except Exception as e:
    print(f"[BOOT] core import fail {e} {traceback.format_exc()}")
    CORE_OK = False

LOCK = Lock()
STATE_FILE = "state_v34.json"
STATE = {
    "vorauswahl_queue": [],
    "turtle_cursor": 0,
    "splinter_inspection": [],
    "hubble_scores": [],
    "hubble_indices": {},
    "hubble_history": [],
    "rsi_history": {},
    "ath_memory": {},
    "paper_trades": [],
    "status": "JAGT",
    "start_ts": time.time(),
    "equity": 100000,
    "rinas": []
}

def load_state():
    global STATE
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                d = json.load(f)
                for k in d:
                    if k in STATE:
                        STATE[k] = d[k]
    except Exception as e:
        print(f"[STATE] load fail {e}")

def save_state(s):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(s, f, default=str)
    except Exception as e:
        print(f"[STATE] save fail {e}")

def json_safe(o):
    if o is None: return None
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o): return 0.0
        return o
    if isinstance(o, dict):
        return {k: json_safe(v) for k,v in o.items()}
    if isinstance(o, (list,tuple)):
        return [json_safe(v) for v in o]
    if isinstance(o, (int, bool, str)): return o
    try:
        fv = float(o)
        if math.isnan(fv) or math.isinf(fv): return 0.0
        return fv
    except:
        return str(o)

hubble_engine = None
rina_engine = None
connector = None
scheduler = None

def init_engines():
    global hubble_engine, rina_engine, connector
    try:
        connector = ExchangeConnector()
        hubble_engine = HubbleEngine()
        rina_engine = RinaEngine()
        print("[BOOT] core OK engines ready")
        return True
    except Exception as e:
        print(f"[BOOT] engine init fail {e} {traceback.format_exc()}")
        return False

ALL_SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","AVAXUSDT","LINKUSDT","ARBUSDT","WIFUSDT","PEPEUSDT","BONKUSDT","SEIUSDT",
    "SUIUSDT","TIAUSDT","ENAUSDT","JUPUSDT","PYTHUSDT","FETUSDT","RENDERUSDT","TAOUSDT","INJUSDT","RNDRUSDT",
    "DOGEUSDT","SHIBUSDT","ADAUSDT","DOTUSDT","MATICUSDT","OPUSDT","ATOMUSDT","NEARUSDT","APTUSDT","LTCUSDT",
    "ETCUSDT","XRPUSDT","BCHUSDT","FILUSDT","UNIUSDT","AAVEUSDT","MKRUSDT","STXUSDT","IMXUSDT","GALAUSDT",
    "SANDUSDT","MANAUSDT","AXSUSDT","FLOWUSDT","CHZUSDT","ENJUSDT","CRVUSDT","COMPUSDT","SNXUSDT","1INCHUSDT",
    "DYDXUSDT","BLURUSDT","WLDUSDT","ARKMUSDT","STRKUSDT","JTOUSDT","FLOKIUSDT","MEMEUSDT","ORDIUSDT","SATSUSDT",
    "BOMEUSDT","NOTUSDT","DOGSUSDT","TONUSDT","TRXUSDT"
]

def safe_get(sym):
    try:
        d = get_market_data(sym)
        price = float(d.get("price",0) or d.get("last",0) or d.get("close",0) or 0)
        if price==0 and connector and hasattr(connector,'exchanges'):
            for ex_name in ['binance','bybit','okx']:
                try:
                    if ex_name in connector.exchanges:
                        ticker = connector.exchanges[ex_name].fetch_ticker(sym)
                        price = float(ticker.get('last',0) or 0)
                        if price>0: break
                except: continue
        ath = float(d.get("ath",0) or d.get("all_time_high",0) or 0)
        ath_dd = float(d.get("ath_dd",0) or 0)
        if price>0 and ath>0:
            ath_dd = ((price/ath -1)*100)
        if ath_dd==0:
            ath_dd = -35.0
        if price>0:
            return {"symbol":sym,"price":price,"ath_dd":round(ath_dd,1),"ath":ath,"ok":True}
    except: pass
    return {"symbol":sym,"price":0,"ath_dd":-35,"ok":False}

def run_turtle_scan():
    global STATE
    try:
        with LOCK:
            cursor = STATE.get("turtle_cursor",0)
            batch = ALL_SYMBOLS[cursor:cursor+20]
            STATE["turtle_cursor"]=0 if cursor+20>=len(ALL_SYMBOLS) else cursor+20
            cur = STATE["turtle_cursor"]
        print(f"[TURTLE] SCAN cursor {cur} batch {batch[0]}..{batch[-1]}")
        found=[]
        for sym in batch:
            try:
                r = safe_get(sym)
                if r.get("ok") and r.get("price",0)>0:
                    found.append(json_safe(r))
                    print(f"[TURTLE] + {sym} price {r['price']}")
                time.sleep(0.3)
            except Exception as e:
                print(f"[TURTLE] {sym} fail {e}")
        with LOCK:
            existing = {x["symbol"]:x for x in STATE.get("vorauswahl_queue",[]) if isinstance(x,dict)}
            for f in found:
                existing[f["symbol"]]=f
            STATE["vorauswahl_queue"]=list(existing.values())[-100:]
            save_state(STATE)
        print(f"[TURTLE] DONE found {len(found)} total {len(STATE['vorauswahl_queue'])}")
        return found
    except Exception as e:
        print(f"[TURTLE] fatal {e} {traceback.format_exc()}")
        return []

def run_splinter_inspection():
    global STATE
    try:
        with LOCK:
            queue = STATE.get("vorauswahl_queue",[])[:8]
        if not queue:
            return []
        res=[]
        for item in queue:
            try:
                sym = item["symbol"] if isinstance(item,dict) else item
                price = item.get("price",0) if isinstance(item,dict) else 0
                res.append(json_safe({"symbol":sym,"ok":price>0,"price":price,"ath_dd":item.get("ath_dd",-35) if isinstance(item,dict) else -35}))
            except:
                continue
            time.sleep(0.2)
        with LOCK:
            STATE["splinter_inspection"]=res
            save_state(STATE)
        print(f"[SPLINTER] DONE {len(res)}/8")
        return res
    except Exception as e:
        print(f"[SPLINTER] {e}")
        return []

def run_hubble_inspection():
    global STATE
    try:
        with LOCK:
            queue = STATE.get("vorauswahl_queue",[])[:12]
        if not queue:
            return []
        indices = {}
        try:
            indices = hubble_engine.fetch_indices() if hubble_engine else {}
        except:
            indices={}
        out=[]
        for item in queue:
            try:
                sym = item["symbol"] if isinstance(item,dict) else item
                price = float(item.get("price",0) if isinstance(item,dict) else 0)
                if price==0:
                    sg = safe_get(sym)
                    price = sg.get("price",0)
                rsi=50; bb=0.5
                try:
                    ohlc_24h, ohlc_30d, ohlc_180d = get_ohlc_three_windows(sym)
                    if ohlc_24h:
                        closes = ohlc_24h.get('close',[])
                        if len(closes)>5:
                            rsi = calc_rsi(closes) or 50
                            bb = calc_bollinger_width(ohlc_24h) or 0.5
                except:
                    pass
                item_dict={"symbol":sym,"price":price,"ath_dd":item.get("ath_dd",-35) if isinstance(item,dict) else -35}
                if hubble_engine:
                    score_dict = hubble_engine.calc_hubble_score(sym, item_dict, None, None, None, None, bb, rsi, {"verdict":"NEUTRAL"})
                    score_dict["price"]=price
                    if score_dict.get("score",0)>=45:
                        score_dict["ready"]=True
                    out.append(json_safe(score_dict))
                else:
                    out.append(json_safe({"symbol":sym,"price":price,"score":55,"ready":True,"ath_dd":item_dict["ath_dd"]}))
                time.sleep(0.3)
            except Exception as e:
                print(f"[HUBBLE] {sym} {e}")
        with LOCK:
            STATE["hubble_scores"]=sorted(out, key=lambda x: x.get("score",0), reverse=True)
            STATE["hubble_indices"]=indices
            STATE["hubble_history"].append({"ts":datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),"scores":STATE["hubble_scores"][:10]})
            STATE["hubble_history"]=STATE["hubble_history"][-50:]
            save_state(STATE)
        print(f"[HUBBLE] scores {len(out)} ready {len([h for h in out if h.get('ready')])}")
        return STATE["hubble_scores"]
    except Exception as e:
        print(f"[HUBBLE] fatal {e} {traceback.format_exc()}")
        return []

def paper_monitor_positions():
    global STATE
    try:
        with LOCK:
            scores = STATE.get("hubble_scores",[])
            paper = STATE.get("paper_trades",[])
        ready = [s for s in scores if s.get("ready")]
        if not ready:
            return
        top = ready[0]
        sym = top["symbol"]
        open_syms = [t.get("symbol") for t in paper if t.get("status")=="OPEN"]
        if sym in open_syms:
            return
        new_trade={
            "symbol":sym,
            "price":top.get("price",0),
            "score":top.get("score",0),
            "status":"OPEN",
            "opened":datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
            "pnl":0,
            "ath_dd":top.get("ath_dd",0)
        }
        try:
            if hasattr(paper_executor,'open_paper_trade'):
                paper_executor.open_paper_trade(sym, top.get("price",0), top.get("score",0))
        except:
            pass
        with LOCK:
            STATE["paper_trades"].append(new_trade)
            STATE["paper_trades"]=STATE["paper_trades"][-20:]
            save_state(STATE)
        print(f"[PAPER] OPEN {sym} score {top.get('score')} price {top.get('price')}")
    except Exception as e:
        print(f"[PAPER] fail {e}")

async def background_boot():
    await asyncio.sleep(2)
    try:
        load_state()
        init_engines()
        run_turtle_scan()
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        global scheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(lambda: asyncio.create_task(asyncio.to_thread(paper_monitor_positions)), 'interval', seconds=30)
        scheduler.add_job(lambda: asyncio.create_task(asyncio.to_thread(run_turtle_scan)), 'interval', minutes=2)
        scheduler.add_job(lambda: asyncio.create_task(asyncio.to_thread(run_splinter_inspection)), 'interval', minutes=5)
        scheduler.add_job(lambda: asyncio.create_task(asyncio.to_thread(run_hubble_inspection)), 'interval', minutes=5)
        scheduler.add_job(lambda: asyncio.create_task(asyncio.to_thread(hubble_engine.fetch_indices)) if hubble_engine else None, 'interval', minutes=10)
        scheduler.start()
        print(f"[BOOT] V3.4.7e FINAL BOOT={datetime.now(ZoneInfo('Europe/Berlin')).isoformat()} queue={len(STATE.get('vorauswahl_queue',[]))}")
        await asyncio.to_thread(run_hubble_inspection)
        await asyncio.to_thread(run_splinter_inspection)
    except Exception as e:
        print(f"[BOOT] fail {e} {traceback.format_exc()}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[BOOT] Lifespan start - port bound")
    asyncio.create_task(background_boot())
    yield
    print("[BOOT] Shutdown")

app = FastAPI(lifespan=lifespan, title="Leonardo V3.4.7e")

@app.get("/api/v34/health")
def health():
    with LOCK:
        return JSONResponse(json_safe({"ok":True,"queue":len(STATE.get("vorauswahl_queue",[])),"hubble":len(STATE.get("hubble_scores",[])),"status":STATE.get("status","JAGT")}))

@app.get("/api/v34/turtles")
def api_turtles():
    try:
        with LOCK:
            q = STATE.get("vorauswahl_queue",[])[:100]
        return JSONResponse(json_safe({"queue":q,"cnt":len(q),"cursor":STATE.get("turtle_cursor",0)}))
    except Exception as e:
        print(f"[API TURTLES] {e}")
        return JSONResponse({"queue":[],"cnt":0,"cursor":0})

@app.get("/api/v34/splinter")
def api_splinter():
    try:
        with LOCK:
            ins = STATE.get("splinter_inspection",[])
        return JSONResponse(json_safe({"inspection":ins}))
    except:
        return JSONResponse({"inspection":[]})

@app.get("/api/v34/hubble")
def api_hubble():
    try:
        with LOCK:
            scores = STATE.get("hubble_scores",[])[:20]
            indices = STATE.get("hubble_indices",{})
        return JSONResponse(json_safe({"scores":scores,"indices":indices}))
    except:
        return JSONResponse({"scores":[],"indices":{}})

@app.get("/api/v34/rina")
def api_rina():
    try:
        with LOCK:
            r = STATE.get("rinas",[])
        return JSONResponse(json_safe({"rinas":r}))
    except:
        return JSONResponse({"rinas":[]})

@app.get("/api/v34/debug")
def api_debug():
    try:
        with LOCK:
            return JSONResponse(json_safe({
                "queue_cnt":len(STATE.get("vorauswahl_queue",[])),
                "cursor":STATE.get("turtle_cursor",0),
                "hubble_cnt":len(STATE.get("hubble_scores",[])),
                "ready_cnt":len([s for s in STATE.get("hubble_scores",[]) if s.get("ready")]),
                "paper_trades":STATE.get("paper_trades",[])[-10:],
                "status":STATE.get("status","JAGT"),
                "uptime_sec":int(time.time()-STATE.get("start_ts",time.time())),
                "equity":STATE.get("equity",100000)
            }))
    except Exception as e:
        return JSONResponse({"queue_cnt":0,"status":"ERROR","error":str(e)[:200]})

@app.get("/", response_class=HTMLResponse)
def root():
    for p in ["dashboard_v34_hubble.html","dashboard_v34_hubble_rina.html","./dashboard_v34_hubble.html","/opt/render/project/src/dashboard_v34_hubble.html"]:
        if os.path.exists(p):
            try:
                with open(p,"r",encoding="utf-8") as f:
                    return HTMLResponse(f.read())
            except:
                continue
    return HTMLResponse("""
    <html><body style='background:#000;color:#39ff14;font-family:monospace;padding:20px'>
    <h1>Leonardo V3.4.7e LIVE</h1>
    <p>Dashboard file not found - push dashboard_v34_hubble.html ins Repo root</p>
    <p><a href='/api/v34/debug'>debug</a> | <a href='/api/v34/turtles'>turtles</a></p>
    </body></html>
    """)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard2():
    return root()
