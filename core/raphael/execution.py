"""
RAPHAEL EXECUTION + WIZDRAW HANDLER - V3.4 FIXED
- JSON Safe
- BE nach +1.5%
- WIZDRAW Button MUSS immer funktionieren
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import uuid
from core.donatello.persistent_state import save_state

def open_position(symbol: str, data: dict, meta: dict, STATE: dict, splinter_decision=None):
    """
    V3.4: Entry mit Splinter Entscheidung (Hold Modus + SL Relativ)
    """
    price = float(data.get("price",0))
    if price==0: return None

    # SL relativ aus Splinter oder fallback
    if splinter_decision:
        sl_mult = splinter_decision.sl_multiplier
        hold_mode = splinter_decision.hold_mode
        max_hours = splinter_decision.max_hold_hours
        max_dd = splinter_decision.max_drawdown_pct
    else:
        sl_mult = 1.5
        hold_mode = "MITTEL"
        max_hours = 24
        max_dd = -1.2

    atr = float(meta.get("atr", price*0.015))
    sl_dist = atr * sl_mult
    sl_price = price + sl_dist if "SHORT" in str(meta.get("side","SHORT")) or True else price - sl_dist
    # Für Short: SL über Entry, da fallend. Für Long invert. V3.4 ist primär Short/Dip
    # Wir traden fallende Coins als Short oder Long Dip? Hier Short Logik:
    # Wenn wir auf fallende setzen = SHORT
    sl_price = price * (1 + sl_dist/price)  # Short SL über Entry

    pos = {
        "id": str(uuid.uuid4())[:8],
        "symbol": symbol,
        "entry": price,
        "current_price": price,
        "qty": 0.03 * 2, # 3%*2x
        "margin": STATE["equity"]*0.03,
        "sl": sl_price,
        "sl_mult": sl_mult,
        "tp1": price * 0.96, # kein fixer TP mehr, aber für Anzeige
        "tp1_done": False,
        "trailing_active": False,
        "pnl_pct": 0.0,
        "pnl_usd": 0.0,
        "hold_mode": hold_mode,
        "max_hold_hours": max_hours,
        "max_drawdown": max_dd,
        "entry_time": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
        "feed_source": data.get("source","binance"),
        "splinter_meta": splinter_decision.meta if splinter_decision else {},
        "be_triggered": False
    }
    STATE["open_positions"].append(pos)
    STATE["trades_today"] += 1
    STATE["last_trade_end"] = None
    save_state(STATE)
    return pos

def monitor_positions(get_market_data_fn, STATE: dict):
    """Alle 20 Sek: PnL updaten + BE nach +1.5%"""
    try:
        for pos in STATE.get("open_positions",[]):
            try:
                data = get_market_data_fn(pos["symbol"])
                curr = float(data.get("price", pos["current_price"]))
                pos["current_price"] = curr
                # Short PnL: (Entry - Current)/Entry
                pnl_pct = (pos["entry"] - curr)/pos["entry"]*100 * 2.0 # leverage 2x
                pos["pnl_pct"] = pnl_pct
                pos["pnl_usd"] = STATE["equity"]*0.03 * pnl_pct/100

                # BE nach +1.5% Gewinn
                if pnl_pct >= 1.5 and not pos.get("be_triggered"):
                    pos["sl"] = pos["entry"]  # BE
                    pos["be_triggered"] = True
                    pos["trailing_active"] = True

                # Max Drawdown Check
                if pnl_pct <= pos.get("max_drawdown", -1.5):
                    # Auto close bei MaxDD
                    close_position(pos, curr, f"MaxDD {pnl_pct:.2f}% Hold {pos['hold_mode']}", STATE)
            except Exception as e:
                print(f"monitor fail {pos['symbol']} {e}")
        save_state(STATE)
    except Exception as e:
        print(f"monitor_positions error {e}")

def close_position(pos: dict, price: float, reason: str, STATE: dict):
    pnl_pct = pos.get("pnl_pct",0)
    pnl_usd = pos.get("pnl_usd",0)
    STATE["closed_today"].append({
        "symbol": pos["symbol"],
        "reason": reason,
        "pnl_pct": pnl_pct,
        "pnl_usd": pnl_usd,
        "time": datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
    })
    STATE["daily_pnl_pct"] += pnl_pct
    STATE["daily_pnl_usd"] += pnl_usd
    STATE["equity"] += pnl_usd
    STATE["open_positions"] = [p for p in STATE["open_positions"] if p["id"] != pos["id"]]
    STATE["last_trade_end"] = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
    if pnl_pct < 0:
        STATE["last_loss_time"] = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
    save_state(STATE)

def wizdraw_manual_close(call_id: str, STATE: dict, telegram_fn=None):
    """
    WIZDRAW - MANUAL CLOSE - MUSS IMMER FUNKTIONIEREN
    Kein Confirm, direkt Market
    """
    for pos in STATE.get("open_positions",[]):
        if pos["id"] == call_id or pos["symbol"] == call_id:
            curr = pos["current_price"]
            pnl = pos["pnl_pct"]
            # Market close simulation
            close_position(pos, curr, "WIZDRAW MANUAL", STATE)
            # Feedback für Splinter
            STATE["wizdraw_feedback"].append({
                "symbol": pos["symbol"],
                "pnl": pnl,
                "hold_mode": pos.get("hold_mode"),
                "time": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
                "reason": "WIZDRAW"
            })
            save_state(STATE)
            if telegram_fn:
                try:
                    telegram_fn(f"🧙 WIZDRAW closed: {pos['symbol']} {pnl:+.2f}% Hold {pos.get('hold_mode')}")
                except: pass
            return {"closed": True, "symbol": pos["symbol"], "pnl": pnl}
    return {"closed": False, "error": "Call not found"}
