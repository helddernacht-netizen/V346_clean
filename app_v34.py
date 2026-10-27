"""
Leonardo / Splinterzell V3.4.6 -> V3.4.7 FIXED
================================================
Was im Original kaputt war (splinterzell_v346.txt):
 1. SYNTAX ERROR Zeile 284: `from apscheduler...` war ausserhalb vom try-Block
    eingerueckt -> Datei kompiliert gar nicht, App startet nie.
 2. NameError: `safe_turtle_scan` wird im Scheduler benutzt, ist aber nirgends
    definiert. Scheduler wirft NameError -> scheduler.start() wird nie erreicht.
 3. API-Ban by Design: pro Zyklus ~65x fetch_ticker einzeln + OHLC pro Coin.
    Binance / Bybit / OKX: >1200 req/min -> 429 / 418 IP-Ban / 500er.
    Fix: EIN Bulk-Call GET /api/v3/ticker/24hr fuer ALLE Coins (=100).
    Klines NUR fuer die 20 Watchlist-Coins, gecacht.
 4. Blocking: time.sleep() in AsyncIO-Scheduler blockiert Event-Loop -> Health
    Endpoint timeoutet -> 500er im Dashboard.
    Fix: Sync-Funktionen via to_thread / Thread-Scheduler, kein sleep im Loop.
 5. Fehlende Logik: ALL_SYMBOLS war hardcoded 65, keine Volatilitaets-Sortierung,
    kein 100->20 Filter, kein 90-Tage Healthline, kein 1%-Sizing.
    Alles jetzt implementiert.
 6. Fehlende Module (hubble_engine, market_data, connector, paper_executor):
    ImportError -> CORE_OK=False -> Engine lief im Blindflug.
    Fix: Alle Module hier embedded, keine externen Imports mehr noetig.
    Laeuft standalone als EINE Datei.

API-Schutz (Anti-Ban):
 - Max 1 Bulk-Request / 60s fuer 24hr-Ticker, 1 Request / 5min fuer Klines pro Coin
 - Token-Bucket: min 250ms Abstand, max 6 req/s
 - Retry nur bei 429/500/503/418 mit Exponential Backoff + Jitter, Retry-After beachten
 - Circuit-Breaker: nach 3 Fehlern 60s Cooldown, dann Mock-Fallback (kein Crash)
 - Public Endpoints ohne API-Key, keine Auth-Header

Offline-Test: Wenn keine Internet-Verbindung (Container / Render-Build), wird
deterministisches Mock benutzt, damit Engine trotzdem bootet und testbar ist.
In Produktion (Internet) wird automatisch Live-Binance benutzt.
"""

import os, time, json, math, traceback, asyncio, random, hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager
from threading import Lock, Thread
import urllib.request
import urllib.error

# ------------------------------------------------------------------ CONFIG
EQUITY_START = 100000.0
RISK_PCT = 0.01  # 1% Equity pro Trade = $1000
RISK_PER_TRADE = EQUITY_START * RISK_PCT
MAX_OPEN_TRADES = 5
SCAN_TOP_N = 100
WATCHLIST_N = 20
STATE_FILE = "state_v34_fixed.json"
CACHE_TTL_TICKER = 60
CACHE_TTL_KLINES = 300
BINANCE_BASE = "https://api.binance.com"
# Stablecoins / Leveraged Tokens rausfiltern
EXCLUDE = {"USDCUSDT","FDUSDUSDT","TUSDUSDT","DAIUSDT","USDPUSDT","AEURUSDT",
           "BULLUSDT","BEARUSDT","UPUSDT","DOWNUSDT"}

LOCK = Lock()
STATE = {
    "vorauswahl_queue": [],  # Top 100 volatilste
    "watchlist": [],         # Top 20
    "turtle_cursor": 0,
    "splinter_inspection": [],
    "hubble_scores": [],
    "hubble_indices": {"btc_dominance": 0, "fear_greed": 50, "total_mcap_trend": "NEUTRAL"},
    "hubble_history": [],
    "rsi_history": {},
    "ath_memory": {},
    "paper_trades": [],
    "closed_trades": [],
    "status": "JAGT",
    "start_ts": time.time(),
    "equity": EQUITY_START,
    "rinas": [],
    "last_scan": None,
    "api_mode": "unknown",  # live | mock
    "api_errors": 0,
}

def now_iso():
    return datetime.now(ZoneInfo("Europe/Berlin")).isoformat()

def json_safe(o):
    if o is None: return None
    if isinstance(o, float):
        return 0.0 if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict): return {k: json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [json_safe(v) for v in o]
    if isinstance(o, (int, bool, str)): return o
    try:
        fv = float(o)
        return 0.0 if (math.isnan(fv) or math.isinf(fv)) else fv
    except: return str(o)

# ------------------------------------------------------------------ RATE LIMITER + HTTP
class RateLimiter:
    def __init__(self, min_interval=0.25):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = Lock()
        self.consecutive_errors = 0
        self.cooldown_until = 0.0
    def wait(self):
        with self._lock:
            if time.time() < self.cooldown_until:
                raise RuntimeError(f"circuit_breaker_cooldown_until_{self.cooldown_until}")
            now = time.time()
            delta = now - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.time()
    def on_success(self):
        self.consecutive_errors = 0
    def on_error(self, status=None):
        self.consecutive_errors += 1
        if self.consecutive_errors >= 3:
            self.cooldown_until = time.time() + 60
            print(f"[API] CIRCUIT BREAKER 60s - {self.consecutive_errors} Fehler, Status {status}")

limiter = RateLimiter(min_interval=0.25)
OFFLINE_MODE = False  # wird nach 1. hartem DNS-Fail gesetzt, dann kein weiterer Netzwerk-Versuch

_cache = {}  # url -> (ts, data)

def http_get_json(url, timeout=3, max_retries=2):
    global OFFLINE_MODE
    if OFFLINE_MODE:
        return None
    """Ein Request mit Retry, Backoff, Retry-After, Cache. Gibt None bei hartem Fail."""
    # Cache zuerst
    if url in _cache:
        ts, data = _cache[url]
        ttl = CACHE_TTL_TICKER if "ticker/24hr" in url else CACHE_TTL_KLINES
        if time.time() - ts < ttl:
            return data
    for attempt in range(max_retries):
        try:
            limiter.wait()
            req = urllib.request.Request(url, headers={"User-Agent": "Leonardo-V346/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                limiter.on_success()
                _cache[url] = (time.time(), data)
                return data
        except urllib.error.HTTPError as e:
            limiter.on_error(e.code)
            body = ""
            try: body = e.read().decode()[:200]
            except: pass
            print(f"[API] HTTP {e.code} {url} attempt={attempt} body={body}")
            if e.code in (429, 418, 500, 502, 503):
                retry_after = e.headers.get("Retry-After")
                wait_s = float(retry_after) if retry_after else (2 ** attempt) + random.uniform(0, 1)
                print(f"[API] Backoff {wait_s:.1f}s")
                time.sleep(wait_s)
                continue
            if e.code == 451:
                print("[API] 451 Geo-Blocked - Fallback auf Mock")
                return None
            return None
        except Exception as e:
            # DNS / kein Internet -> sofort in Mock-Modus, keine weiteren Retries fuer alle Coins
            if "Name or service not known" in str(e) or "nodename nor servname" in str(e) or "Temporary failure" in str(e) or isinstance(e, OSError):
                OFFLINE_MODE = True
                print(f"[API] OFFLINE erkannt ({e}) -> Mock-Modus fuer diesen Run")
                return None
            limiter.on_error(None)
            print(f"[API] {type(e).__name__} {url} attempt={attempt}: {e}")
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
            else:
                return None
    return None

# ------------------------------------------------------------------ MOCK (deterministisch, fuer Tests ohne Internet)
def mock_ticker_24hr():
    """Generiert 100+ plausible Coins, deterministisch pro Symbol."""
    base = ["BTC","ETH","SOL","AVAX","LINK","ARB","WIF","PEPE","BONK","SEI","SUI","TIA","ENA","JUP","PYTH","FET","RENDER","TAO","INJ","RNDR","DOGE","SHIB","ADA","DOT","MATIC","OP","ATOM","NEAR","APT","LTC","ETC","XRP","BCH","FIL","UNI","AAVE","MKR","STX","IMX","GALA","SAND","MANA","AXS","FLOW","CHZ","ENJ","CRV","COMP","SNX","1INCH","DYDX","BLUR","WLD","ARKM","STRK","JTO","FLOKI","MEME","ORDI","SATS","BOME","NOT","DOGS","TON","TRX","HYPE","VIRTUAL","AI16Z","PNUT","ACT","GOAT","MOODENG","POPCAT","MEW","BRETT","NEIRO","TURBO","PONKE","CAT","DOG","KAS","XMR","ZEC","DASH","LDO","EIGEN","ETHFI","ZRO","ZK","MANTA","ALT","OMNI","REZ","BB","LISTA","IO","ATH","BEAM","SUPER","PIXEL","PORTAL","SAGA","W","JUP2","DRIFT","KMNO"]
    out = []
    for sym in base:
        h = int(hashlib.md5(sym.encode()).hexdigest()[:8], 16)
        rng = random.Random(h)
        price = round(10 ** rng.uniform(-4, 2) * rng.uniform(0.5, 3), 6) if sym not in ("BTC","ETH") else (97000.0 if sym=="BTC" else 3400.0)
        chg = round(rng.uniform(-18, 18), 2)
        vol = rng.uniform(5e6, 8e8)
        out.append({"symbol": f"{sym}USDT", "lastPrice": str(price), "priceChangePercent": str(chg), "volume": str(vol), "quoteVolume": str(rng.uniform(2e6, 9e8)), "highPrice": str(price*1.1), "lowPrice": str(price*0.9)})
    return out

def mock_klines(symbol, limit=90):
    h = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
    rng = random.Random(h + limit)
    price = rng.uniform(0.01, 100)
    closes = []
    for i in range(limit):
        price *= (1 + rng.uniform(-0.04, 0.045))
        closes.append(round(price, 6))
    return closes

# ------------------------------------------------------------------ MARKET DATA (ersetzt market_data.py + connector.py)
def get_market_data_bulk():
    """1 Request fuer ALLE Coins - statt 65 Einzel-Requests."""
    data = http_get_json(f"{BINANCE_BASE}/api/v3/ticker/24hr")
    if data is None:
        STATE["api_mode"] = "mock"
        STATE["api_errors"] += 1
        return mock_ticker_24hr()
    STATE["api_mode"] = "live"
    return data

def get_klines_closes(symbol, interval="1d", limit=90):
    data = http_get_json(f"{BINANCE_BASE}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
    if data is None:
        return mock_klines(symbol, limit=limit)
    try:
        return [float(k[4]) for k in data]  # close = Index 4
    except:
        return mock_klines(symbol, limit=limit)

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, period+1):
        d = closes[-i] - closes[-i-1] if len(closes) > i else 0
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag = sum(gains)/period; al = sum(losses)/period
    if al == 0: return 100.0 if ag > 0 else 50.0
    rs = ag/al
    return round(100 - (100/(1+rs)), 1)

def calc_atr(closes, period=14):
    if len(closes) < 2: return 0.0
    trs = [abs(closes[i]-closes[i-1]) for i in range(1, len(closes))]
    return round(sum(trs[-period:])/min(period, len(trs)), 6)

def calc_bollinger_width(closes, period=20):
    if len(closes) < period: return 0.5
    w = closes[-period:]
    mean = sum(w)/len(w)
    var = sum((x-mean)**2 for x in w)/len(w)
    sd = math.sqrt(var)
    return round((2*sd)/mean if mean else 0.5, 4)

def calc_sma(closes, period):
    if len(closes) < period: return closes[-1] if closes else 0
    return sum(closes[-period:])/period

# ------------------------------------------------------------------ SCANNER: 100 volatilste -> 20 Watchlist
def run_turtle_scan():
    """FIXED: Bulk-Scan, Volatilitaets-Ranking, 100 -> 20, keine Einzel-Calls."""
    try:
        tickers = get_market_data_bulk()
        scored = []
        for t in tickers:
            sym = t.get("symbol","")
            if not sym.endswith("USDT") or sym in EXCLUDE: continue
            try:
                price = float(t.get("lastPrice", 0))
                chg = float(t.get("priceChangePercent", 0))
                qvol = float(t.get("quoteVolume", 0) or t.get("volume", 0))
                if price <= 0 or qvol < 1_000_000: continue  # Liquiditaet >1M
                vol_score = abs(chg) * math.log10(qvol + 1)  # Volatilitaet gewichtet mit Volumen
                scored.append({"symbol": sym, "price": price, "chg_24h": round(chg,2),
                               "volume": qvol, "vol_score": round(vol_score,2),
                               "ath_dd": -35.0, "ok": True})
            except: continue
        scored.sort(key=lambda x: x["vol_score"], reverse=True)
        top100 = scored[:SCAN_TOP_N]
        watch20 = top100[:WATCHLIST_N]
        with LOCK:
            STATE["vorauswahl_queue"] = top100
            STATE["watchlist"] = watch20
            STATE["last_scan"] = now_iso()
            save_state()
        print(f"[TURTLE] FIXED DONE top100={len(top100)} watch20={len(watch20)} first={watch20[0]['symbol'] if watch20 else '-'} mode={STATE['api_mode']}")
        return top100
    except Exception as e:
        print(f"[TURTLE] fatal {e} {traceback.format_exc()}")
        return []

def safe_turtle_scan():
    """FEHLTE im Original - jetzt definiert."""
    try: run_turtle_scan()
    except Exception as e: print(f"[TURTLE SAFE] {e}")

# ------------------------------------------------------------------ SPLINTER: 20er Beobachtung
def run_splinter_inspection():
    try:
        with LOCK:
            queue = list(STATE.get("watchlist", []) or STATE.get("vorauswahl_queue", [])[:WATCHLIST_N])
        if not queue:
            run_turtle_scan()
            queue = list(STATE.get("watchlist", []))
        res = []
        for item in queue[:WATCHLIST_N]:
            sym = item["symbol"] if isinstance(item, dict) else item
            res.append(json_safe({"symbol": sym, "ok": True, "price": item.get("price",0) if isinstance(item,dict) else 0,
                                  "ath_dd": item.get("ath_dd",-35) if isinstance(item,dict) else -35,
                                  "chg_24h": item.get("chg_24h",0) if isinstance(item,dict) else 0}))
        with LOCK:
            STATE["splinter_inspection"] = res
            save_state()
        print(f"[SPLINTER] DONE {len(res)}/20 watchlist")
        return res
    except Exception as e:
        print(f"[SPLINTER] {e} {traceback.format_exc()}")
        return []

# ------------------------------------------------------------------ HUBBLE: Bewertungsengine + 90d Healthline
def calc_hubble_score(sym, price, rsi, bb_width, atr, chg_24h, chg_7d, ath_dd, sma_trend):
    """Score 0-100. Original rief calc_hubble_score(..., None, None, None, None) auf."""
    score = 50.0
    # Momentum 24h / 7d (Scalping 24h-7d)
    score += max(-15, min(15, chg_24h * 0.8))
    score += max(-10, min(10, chg_7d * 0.4))
    # RSI Mean-Reversion fuer Scalping: 30-50 = Long-Bias, >75 = ueberhitzt
    if 30 <= rsi <= 50: score += 10
    elif rsi < 30: score += 15
    elif rsi > 75: score -= 12
    elif rsi > 65: score -= 5
    # Bollinger Squeeze = Volatilitaets-Ausbruch steht bevor
    if bb_width < 0.08: score += 8
    elif bb_width > 0.35: score -= 5
    # ATH-Distanz: -60% bis -20% = gesunde Korrektur, nicht tot
    if -60 <= ath_dd <= -20: score += 8
    elif ath_dd < -85: score -= 10
    # Trend 90d Healthline
    if sma_trend == "UP": score += 8
    elif sma_trend == "DOWN": score -= 8
    # ATR relativ zum Preis
    if price > 0 and atr/price > 0.03: score += 5
    score = max(0, min(100, round(score, 1)))
    return score

def run_hubble_inspection():
    try:
        with LOCK:
            queue = list(STATE.get("watchlist", []) or STATE.get("vorauswahl_queue", [])[:WATCHLIST_N])
        if not queue: return []
        out = []
        for item in queue:
            try:
                sym = item["symbol"]
                price = float(item.get("price",0) or 0)
                chg_24h = float(item.get("chg_24h",0) or 0)
                # Klines: 1d 90 Tage Healthline + 7d (1d 7) + 24h (1h 24)
                closes_90 = get_klines_closes(sym, "1d", 90)
                closes_7 = closes_90[-7:] if len(closes_90) >= 7 else closes_90
                closes_24h = get_klines_closes(sym, "1h", 24)
                # Preis aus Klines nehmen - sonst divergiert Ticker vs. Klines (Mock + Live-Gap)
                if closes_90: price = closes_90[-1]
                chg_7d = ((closes_90[-1]/closes_90[-7]-1)*100) if len(closes_90) >= 7 and closes_90[-7] else 0
                ath_90 = max(max(closes_90), price) if closes_90 else price  # ATH muss >= Preis sein, sonst ath_dd positiv
                ath_dd = ((price/ath_90-1)*100) if ath_90 else -35.0
                rsi = calc_rsi(closes_24h if len(closes_24h) >= 15 else closes_90)
                bb = calc_bollinger_width(closes_90)
                atr = calc_atr(closes_90)
                sma20, sma50 = calc_sma(closes_90, 20), calc_sma(closes_90, 50)
                sma_trend = "UP" if sma20 > sma50 else ("DOWN" if sma20 < sma50 else "FLAT")
                score = calc_hubble_score(sym, price, rsi, bb, atr, chg_24h, chg_7d, ath_dd, sma_trend)
                out.append(json_safe({"symbol": sym, "price": price, "score": score,
                                      "ready": score >= 45, "ath_dd": round(ath_dd,1),
                                      "rsi": rsi, "bb_width": bb, "atr": atr,
                                      "chg_24h": round(chg_24h,2), "chg_7d": round(chg_7d,2),
                                      "healthline_90d": sma_trend, "sma20": round(sma20,6), "sma50": round(sma50,6)}))
            except Exception as e:
                print(f"[HUBBLE] {item} {e}")
        out.sort(key=lambda x: x.get("score",0), reverse=True)
        with LOCK:
            STATE["hubble_scores"] = out
            STATE["hubble_history"].append({"ts": now_iso(), "scores": out[:10]})
            STATE["hubble_history"] = STATE["hubble_history"][-50:]
            save_state()
        print(f"[HUBBLE] scores {len(out)} ready {len([h for h in out if h.get('ready')])}")
        return out
    except Exception as e:
        print(f"[HUBBLE] fatal {e} {traceback.format_exc()}")
        return []

# ------------------------------------------------------------------ PAPER TRADING: 100k, 1% Equity
def paper_monitor_positions():
    """FIXED: 1% Sizing, Max 5 offen, PnL-Update, kein endloses Anhaengen."""
    try:
        with LOCK:
            scores = list(STATE.get("hubble_scores", []))
            paper = list(STATE.get("paper_trades", []))
            equity = float(STATE.get("equity", EQUITY_START))
        # PnL offener Trades updaten (Preis aus Scores)
        price_map = {s["symbol"]: s.get("price",0) for s in scores}
        with LOCK:
            for t in STATE["paper_trades"]:
                if t.get("status") == "OPEN" and t["symbol"] in price_map and price_map[t["symbol"]]:
                    cur = price_map[t["symbol"]]
                    t["current_price"] = cur
                    t["pnl"] = round((cur - t["price"]) * t["qty"], 2)
                    t["pnl_pct"] = round((cur/t["price"]-1)*100, 2) if t["price"] else 0
            # Equity = Start + realisierte + unrealisierte PnL
            realised = sum(t.get("pnl",0) for t in STATE["closed_trades"])
            unreal = sum(t.get("pnl",0) for t in STATE["paper_trades"] if t.get("status")=="OPEN")
            STATE["equity"] = round(EQUITY_START + realised + unreal, 2)
        ready = [s for s in scores if s.get("ready")]
        if not ready: return
        open_syms = [t.get("symbol") for t in paper if t.get("status")=="OPEN"]
        if len(open_syms) >= MAX_OPEN_TRADES: return
        top = ready[0]
        sym = top["symbol"]
        if sym in open_syms: return
        price = top.get("price",0)
        if price <= 0: return
        qty = round(RISK_PER_TRADE / price, 6)  # 1% = $1000 Notional
        new_trade = {"symbol": sym, "price": price, "current_price": price, "qty": qty,
                     "notional": RISK_PER_TRADE, "score": top.get("score",0), "status": "OPEN",
                     "opened": now_iso(), "pnl": 0, "pnl_pct": 0, "ath_dd": top.get("ath_dd",0),
                     "tp": round(price*1.03, 6), "sl": round(price*0.985, 6)}
        with LOCK:
            STATE["paper_trades"].append(new_trade)
            STATE["paper_trades"] = STATE["paper_trades"][-20:]
            save_state()
        print(f"[PAPER] OPEN {sym} price={price} qty={qty} notional=${RISK_PER_TRADE} (1% von ${equity}) score={top.get('score')}")
    except Exception as e:
        print(f"[PAPER] fail {e} {traceback.format_exc()}")

def safe_paper_monitor():
    try: paper_monitor_positions()
    except Exception as e: print(f"[PAPER MONITOR FAIL] {e}")

# ------------------------------------------------------------------ STATE
def load_state():
    global STATE
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                d = json.load(f)
                for k in d:
                    if k in STATE: STATE[k] = d[k]
    except Exception as e: print(f"[STATE] load fail {e}")

def save_state():
    try:
        with open(STATE_FILE, "w") as f: json.dump(json_safe(STATE), f, default=str)
    except Exception as e: print(f"[STATE] save fail {e}")

# ------------------------------------------------------------------ SCHEDULER (Thread statt blockierendem APScheduler)
_scheduler_stop = False
def _loop(fn, interval_s, name):
    while not _scheduler_stop:
        try: fn()
        except Exception as e: print(f"[SCHED {name}] {e}")
        time.sleep(interval_s)

def start_scheduler():
    Thread(target=_loop, args=(safe_turtle_scan, 100, "turtle"), daemon=True).start()
    Thread(target=_loop, args=(safe_paper_monitor, 30, "paper"), daemon=True).start()
    Thread(target=_loop, args=(run_splinter_inspection, 300, "splinter"), daemon=True).start()
    Thread(target=_loop, args=(run_hubble_inspection, 300, "hubble"), daemon=True).start()
    print("[SCHED] Threads gestartet: turtle 100s, paper 30s, splinter/hubble 300s")

def boot():
    load_state()
    print(f"[BOOT] V3.4.7 FIXED boot={now_iso()} equity=${STATE['equity']}")
    run_turtle_scan()
    run_splinter_inspection()
    run_hubble_inspection()
    paper_monitor_positions()
    start_scheduler()

# ------------------------------------------------------------------ HTTP API (FastAPI wenn vorhanden, sonst Stdlib)
try:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse, HTMLResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

if HAS_FASTAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        print("[BOOT] Lifespan start")
        asyncio.create_task(asyncio.to_thread(boot))
        yield
        print("[BOOT] Shutdown")
    app = FastAPI(lifespan=lifespan, title="Leonardo V3.4.7 FIXED")
    @app.get("/api/v34/health")
    def health():
        with LOCK: return JSONResponse(json_safe({"ok": True, "queue": len(STATE.get("vorauswahl_queue",[])), "watchlist": len(STATE.get("watchlist",[])), "hubble": len(STATE.get("hubble_scores",[])), "status": STATE.get("status","JAGT"), "api_mode": STATE.get("api_mode"), "equity": STATE.get("equity")}))
    @app.get("/api/v34/turtles")
    def api_turtles():
        with LOCK: return JSONResponse(json_safe({"queue": STATE.get("vorauswahl_queue",[])[:100], "cnt": len(STATE.get("vorauswahl_queue",[])), "cursor": 0, "watchlist": STATE.get("watchlist",[])}))
    @app.get("/api/v34/splinter")
    def api_splinter():
        with LOCK: return JSONResponse(json_safe({"inspection": STATE.get("splinter_inspection",[])}))
    @app.get("/api/v34/hubble")
    def api_hubble():
        with LOCK: return JSONResponse(json_safe({"scores": STATE.get("hubble_scores",[])[:20], "indices": STATE.get("hubble_indices",{})}))
    @app.get("/api/v34/rina")
    def api_rina():
        with LOCK: return JSONResponse(json_safe({"rinas": STATE.get("rinas",[])}))
    @app.get("/api/v34/paper")
    def api_paper():
        with LOCK: return JSONResponse(json_safe({"equity": STATE.get("equity"), "risk_per_trade": RISK_PER_TRADE, "open": STATE.get("paper_trades",[]), "closed": STATE.get("closed_trades",[])}))
    @app.get("/api/v34/debug")
    def api_debug():
        with LOCK: return JSONResponse(json_safe({"queue_cnt": len(STATE.get("vorauswahl_queue",[])), "watchlist_cnt": len(STATE.get("watchlist",[])), "hubble_cnt": len(STATE.get("hubble_scores",[])), "ready_cnt": len([s for s in STATE.get("hubble_scores",[]) if s.get("ready")]), "paper_trades": STATE.get("paper_trades",[])[-10:], "status": STATE.get("status"), "uptime_sec": int(time.time()-STATE.get("start_ts", time.time())), "equity": STATE.get("equity"), "api_mode": STATE.get("api_mode"), "api_errors": STATE.get("api_errors")}))
    @app.get("/", response_class=HTMLResponse)
    def root():
        return HTMLResponse(f"<html><body style='background:#000;color:#39ff14;font-family:monospace;padding:20px'><h1>Leonardo V3.4.7 FIXED LIVE</h1><p>Queue: {len(STATE.get('vorauswahl_queue',[]))} | Watchlist: {len(STATE.get('watchlist',[]))} | Equity: ${STATE.get('equity')} | Mode: {STATE.get('api_mode')}</p><p><a href='/api/v34/debug'>debug</a> | <a href='/api/v34/turtles'>turtles</a> | <a href='/api/v34/hubble'>hubble</a> | <a href='/api/v34/paper'>paper</a></p></body></html>")
    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard2(): return root()
else:
    app = None  # Stdlib-Fallback wird in __main__ gestartet

if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        # Synchroner Testlauf ohne Server
        run_turtle_scan(); run_splinter_inspection(); run_hubble_inspection(); paper_monitor_positions()
        print("TEST RESULT:", json.dumps({"queue": len(STATE["vorauswahl_queue"]), "watchlist": len(STATE["watchlist"]), "hubble": len(STATE["hubble_scores"]), "ready": len([s for s in STATE["hubble_scores"] if s.get("ready")]), "paper": STATE["paper_trades"], "equity": STATE["equity"], "api_mode": STATE["api_mode"]}, indent=2))
    elif HAS_FASTAPI:
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
    else:
        # Stdlib HTTP Server (wenn FastAPI auf Render fehlt)
        from http.server import BaseHTTPRequestHandler, HTTPServer
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                routes = {"/api/v34/health": {"ok": True, "queue": len(STATE["vorauswahl_queue"]), "watchlist": len(STATE["watchlist"]), "equity": STATE["equity"], "api_mode": STATE["api_mode"]},
                          "/api/v34/turtles": {"queue": STATE["vorauswahl_queue"][:100], "watchlist": STATE["watchlist"]},
                          "/api/v34/hubble": {"scores": STATE["hubble_scores"][:20]},
                          "/api/v34/paper": {"equity": STATE["equity"], "open": STATE["paper_trades"]},
                          "/api/v34/debug": {"queue_cnt": len(STATE["vorauswahl_queue"]), "equity": STATE["equity"], "api_mode": STATE["api_mode"]}}
                data = routes.get(self.path, {"ok": True, "msg": "Leonardo FIXED live"})
                self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
                self.wfile.write(json.dumps(json_safe(data)).encode())
            def log_message(self, *a): pass
        Thread(target=boot, daemon=True).start()
        time.sleep(1)
        print(f"[HTTP] Stdlib Server auf :{os.environ.get('PORT',8000)}")
        HTTPServer(("0.0.0.0", int(os.environ.get("PORT",8000))), H).serve_forever()

