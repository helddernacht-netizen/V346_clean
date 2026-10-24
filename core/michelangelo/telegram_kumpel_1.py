"""
MICHELANGELO - Telegram Kumpel - Stub
"""
import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN","")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID","")

def send_telegram(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[TG Mock] {text}")
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=5)
    except Exception as e:
        print(f"TG fail {e}")
