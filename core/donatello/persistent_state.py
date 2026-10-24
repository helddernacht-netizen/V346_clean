import json, os
from datetime import datetime
from zoneinfo import ZoneInfo
DEFAULT_STATE={"equity":100.0,"status":"JAGT","open_positions":[],"closed_today":[],"vorauswahl_queue":[],"hubble_scores":[]}
STATE_FILE=os.path.join(os.path.dirname(__file__),"../../data/relax_state.json")
LOG_FILE=os.path.join(os.path.dirname(__file__),"../../data/relax_log.jsonl")
def load_state():
    return DEFAULT_STATE.copy()
def save_state(s): pass
def log_day(e): pass
