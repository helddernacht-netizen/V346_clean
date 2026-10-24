"""
V3.4 SPLINTERZELLE - Persistent State - FIXED for V34
"""
import json, os
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_STATE = {
    "equity": 100.0,
    "safe_account": 0.0,
    "initial_equity_today": 100.0,
    "daily_pnl_pct": 0.0,
    "daily_pnl_usd": 0.0,
    "trades_today": 0,
    "last_reset_date": datetime.now(ZoneInfo("Europe/Berlin")).date().isoformat(),
    "last_trade_end": None,
    "last_loss_time": None,
    "open_positions": [],
    "closed_today": [],
    "status": "JAGT",
    "status_reason": "Init",
    "dynamic_whitelist": [],
    "whitelist_source": "default",
    "whitelist_details": [],
    "whitelist_updated": "nie",
    # V3.4 NEU
    "vorauswahl_queue": [],  # max 20
    "splinter_inspection": [], # 8 Coins
    "money_flow": {"inflow": 0, "outflow": 0, "net_flow": 0, "usdt_dominance": 0},
    "wizdraw_feedback": []  # manuelle closes zum Lernen
}

STATE_FILE = os.path.join(os.path.dirname(__file__), "../../data/relax_state.json")
LOG_FILE = os.path.join(os.path.dirname(__file__), "../../data/relax_log.jsonl")

def load_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                # merge defaults
                merged = DEFAULT_STATE.copy()
                merged.update(data)
                return merged
    except Exception as e:
        print(f"load_state fail: {e}")
    return DEFAULT_STATE.copy()

def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        print(f"save_state fail: {e}")

def log_day(entry):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except: pass
