
"""
RAPHAEL EXECUTION + WIZDRAW HANDLER - V3.4 ECHT, KEIN TELEGRAM
- BE nach +1.5%
- WIZDRAW muss immer funktionieren
- Hold Modi aus Brainstorm Log
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import uuid
from core.donatello.persistent_state import save_state

def open_position(symbol: str, data: dict, meta: dict, STATE: dict, splinter_decision=None):
    price = float(data.get("price",0))
    if price==0: 
        return None

    if splinter_decision:
        sl_mult = splinter_decision.sl_multiplier
        hold_mode = splinter_decision.hold_mode
        max_hours = splinter_decision.max_hold_hours
        max_dd = splinter_decision.max_drawdown_pct
        target_pct = splinter_decision.target_pct
    else:
        sl_mult = 1.5
        hold_mode = "MITTEL"
        max_hours = 24
        max_dd = -1.2
        target_pct = 4.0

    atr = float(meta.get("atr", price*0.015))
    sl_dist = atr * sl_mult
    
    # V3.4: Wir setzen auf FALLENDE Kurse = SHORT
    # SHORT SL liegt ÜBER Entry: Entry + sl_dist
    sl_price = price + sl_dist

    pos = {
        "id": str(uuid.uuid4())[:8],
        "symbol": symbol,
        "side": "SHORT",
        "entry": price,
        "current_price": price,
        "qty": 0.03 * 2,
        "margin": STATE["equity"]*0.03,
        "sl": sl_price,
        "sl_dist": sl_dist,
        "sl_mult": sl_mult,
        "tp_target_pct": target_pct,
        "tp1": price * (1 - target_pct/100),  # für Anzeige, aber kein fixer TP mehr per Log
        "tp1_done": False,
        "trailing_active": False,
        "pnl_pct": 0.0,
        "pnl_usd": 0.0,
        "hold_mode": hold_mode,
        "max_hold_hours": max_hours,
        "max_drawdown": max_dd,
        "entry_time": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
        "feed_source": data.get("source","binance,coinbase,bybit,okx,kraken"),
        "splinter_meta": splinter_decision.meta if splinter_decision else {},
        "be_triggered": False,
        "bed1_meta": splinter_decision.bed1_meta if splinter_decision else {},
        "bed4_meta": splinter_decision.bed4_meta if splinter_decision else {}
    }
    STATE["open_positions"].append(pos)
    STATE["trades_today"] += 1
    STATE["last_trade_end"] = None
    save_state(STATE)
    print(f"🐢 V3.4 ENTRY {symbol} Hold {hold_mode} SLx{sl_mult} Price {price:.6f}")
    return pos

def monitor_positions(get_market_data_fn, STATE: dict):
    """Alle 20 Sek: PnL updaten + BE nach +1.5% + Hold Logik"""
    try:
        for pos in STATE.get("open_positions",[])[:]:  # copy for safe delete
            try:
                data = get_market_data_fn(pos["symbol"])
                curr = float(data.get("price", pos["current_price"]))
                if curr == 0:
                    continue
                pos["current_price"] = curr
                # Short PnL: (Entry - Current)/Entry *100 * Lev
                pnl_pct = (pos["entry"] - curr)/pos["entry"]*100 * 2.0
                pos["pnl_pct"] = pnl_pct
                pos["pnl_usd"] = STATE["equity"]*0.03 * pnl_pct/100

                # BE nach +1.5% Gewinn sofort auf Entry ziehen - Regel aus Log
                if pnl_pct >= 1.5 and not pos.get("be_triggered"):
                    pos["sl"] = pos["entry"]
                    pos["be_triggered"] = True
                    pos["trailing_active"] = True
                    print(f"BE triggered {pos['symbol']} +{pnl_pct:.2f}%")

                # Treasure Hold Logik: Wenn -0.7% und Mittel/Lang geplant -> NICHT raus
                # Nur Kurz-Hold fliegt bei -0.7% raus, Mittel/Lang hält bis MaxDD -1.5%
                is_kurz = pos.get("hold_mode") == "KURZ"
                max_dd = pos.get("max_drawdown", -1.5)
                
                if pnl_pct <= max_dd:
                    # Max Drawdown erreicht = raus
                    reason = f"MaxDD {pnl_pct:.2f}% Hold {pos['hold_mode']} erreicht"
                    close_position(pos, curr, reason, STATE)
                elif pnl_pct <= -0.7 and is_kurz:
                    # Kurz-Hold bei -0.7% raus, Mittel/Lang hält
                    reason = f"Kurz-Hold -0.7% SL Hold {pos['hold_mode']}"
                    close_position(pos, curr, reason, STATE)

                # Hold Zeit abgelaufen?
                try:
                    entry_dt = datetime.fromisoformat(pos["entry_time"])
                    now = datetime.now(ZoneInfo("Europe/Berlin"))
                    hours_held = (now - entry_dt).total_seconds()/3600
                    if hours_held >= pos.get("max_hold_hours",24):
                        reason = f"Hold Ende {hours_held:.1f}h {pos['hold_mode']}"
                        close_position(pos, curr, reason, STATE)
                except:
                    pass

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
        "time": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
        "hold_mode": pos.get("hold_mode")
    })
    STATE["daily_pnl_pct"] += pnl_pct
    STATE["daily_pnl_usd"] += pnl_usd
    STATE["equity"] += pnl_usd
    STATE["open_positions"] = [p for p in STATE["open_positions"] if p["id"] != pos["id"]]
    STATE["last_trade_end"] = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
    if pnl_pct < 0:
        STATE["last_loss_time"] = datetime.now(ZoneInfo("Europe/Berlin")).isoformat()
    save_state(STATE)
    print(f"CLOSE {pos['symbol']} {reason} PnL {pnl_pct:+.2f}%")

def wizdraw_manual_close(call_id: str, STATE: dict):
    """
    WIZDRAW - MANUAL CLOSE - MUSS IMMER FUNKTIONIEREN
    Kein Confirm, direkt Market, auch wenn Bot in Hold ist
    Nach Close: Splinterzelle lernt daraus
    """
    for pos in STATE.get("open_positions",[])[:]:
        if pos["id"] == call_id or pos["symbol"] == call_id:
            curr = pos["current_price"]
            pnl = pos["pnl_pct"]
            close_position(pos, curr, "WIZDRAW MANUAL", STATE)
            STATE["wizdraw_feedback"].append({
                "symbol": pos["symbol"],
                "pnl": pnl,
                "hold_mode": pos.get("hold_mode"),
                "time": datetime.now(ZoneInfo("Europe/Berlin")).isoformat(),
                "reason": "WIZDRAW",
                "bed1": pos.get("bed1_meta",{}),
                "bed4": pos.get("bed4_meta",{})
            })
            save_state(STATE)
            print(f"🧙 WIZDRAW closed: {pos['symbol']} {pnl:+.2f}% Hold {pos.get('hold_mode')}")
            return {"closed": True, "symbol": pos["symbol"], "pnl": pnl, "hold_mode": pos.get("hold_mode")}
    return {"closed": False, "error": "Call not found"}
