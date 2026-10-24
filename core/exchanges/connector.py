"""
EXCHANGE CONNECTOR - V3.4.6 RINA FINAL
5 Börsen, Public + Kraken Private (optional via ENV)
"""

import ccxt
import pandas as pd
import time
import os
from typing import Optional, Dict, List

class ExchangeConnector:
    def __init__(self):
        self.exchanges = {}
        self.kraken_auth = False
        
        # Public Börsen
        for name in ["binance", "coinbase", "bybit", "okx"]:
            try:
                self.exchanges[name] = getattr(ccxt, name)({"enableRateLimit": True, "options": {"defaultType": "spot"}})
            except: pass
        
        # Kraken - Public oder Private je nach ENV
        try:
            k = os.getenv("KRAKEN_API_KEY","").strip()
            s = os.getenv("KRAKEN_API_SECRET","").strip()
            if k and s:
                self.exchanges["kraken"] = ccxt.kraken({
                    "enableRateLimit": True, 
                    "apiKey": k, 
                    "secret": s
                })
                self.kraken_auth = True
            else:
                self.exchanges["kraken"] = ccxt.kraken({"enableRateLimit": True})
        except: pass

        print(f"[Connector] {list(self.exchanges.keys())} kraken_auth={self.kraken_auth}")

    def normalize_symbol(self, symbol: str, exchange_id: str) -> List[str]:
        tries = []
        base = symbol.replace('USDT','').replace('USD','').replace('/','').replace('-','')
        tries.append(symbol)
        if 'USDT' in symbol:
            tries.append(f"{base}/USDT")
            tries.append(f"{base}/USD")
        elif '/' not in symbol:
            tries.append(f"{symbol}/USDT")
        if exchange_id == 'coinbase':
            tries.append(f"{base}/USD")
            tries.append(f"{base}-USD")
        # unique
        seen = []
        for t in tries:
            if t not in seen:
                seen.append(t)
        return seen

    def fetch_ticker_safe(self, symbol: str) -> Dict[str, Dict]:
        result = {}
        for eid, ex in self.exchanges.items():
            for try_sym in self.normalize_symbol(symbol, eid):
                try:
                    ticker = ex.fetch_ticker(try_sym)
                    if ticker and ticker.get('last') is not None:
                        result[eid] = ticker
                        break
                except:
                    continue
            time.sleep(ex.rateLimit/1000 if hasattr(ex,'rateLimit') else 0.1)
        return result

    def fetch_ohlcv_safe(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> Optional[pd.DataFrame]:
        for eid, ex in self.exchanges.items():
            for try_sym in self.normalize_symbol(symbol, eid):
                try:
                    if not ex.has['fetchOHLCV']:
                        continue
                    ohlcv = ex.fetch_ohlcv(try_sym, timeframe=timeframe, limit=limit)
                    if ohlcv and len(ohlcv) >= 10:
                        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
                        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                        return df
                except:
                    continue
            time.sleep(0.1)
        return None

    def fetch_ohlcv_multi(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> Dict[str, pd.DataFrame]:
        result = {}
        for eid, ex in self.exchanges.items():
            for try_sym in self.normalize_symbol(symbol, eid):
                try:
                    ohlcv = ex.fetch_ohlcv(try_sym, timeframe=timeframe, limit=limit)
                    if ohlcv and len(ohlcv)>=2:
                        df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
                        result[eid] = df
                        break
                except:
                    continue
        return result

    def fetch_funding_rate(self, symbol: str) -> Optional[float]:
        for eid in ['bybit','binance','okx']:
            ex = self.exchanges.get(eid)
            if not ex: continue
            for try_sym in self.normalize_symbol(symbol, eid):
                try:
                    fr = ex.fetch_funding_rate(try_sym)
                    if fr and 'fundingRate' in fr:
                        return float(fr['fundingRate'])
                except:
                    continue
        return None

    def fetch_open_interest(self, symbol: str) -> Optional[float]:
        for eid in ['bybit','binance','okx']:
            ex = self.exchanges.get(eid)
            if not ex: continue
            for try_sym in self.normalize_symbol(symbol, eid):
                try:
                    oi = ex.fetch_open_interest(try_sym)
                    if oi and 'openInterest' in oi:
                        return float(oi['openInterest'])
                except:
                    continue
        return None

    # NEU: Kraken Private
    def fetch_balance_kraken(self):
        if not self.kraken_auth:
            return None
        try:
            bal = self.exchanges["kraken"].fetch_balance()
            return {"usdt": bal.get("total",{}).get("USDT",0), "total": bal.get("total",{})}
        except Exception as e:
            return {"error": str(e)}

# Global Singleton
connector = ExchangeConnector()
