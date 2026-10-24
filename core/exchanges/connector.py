"""
EXCHANGE CONNECTOR - 5 größte Börsen, kein Mock
Binance, Coinbase, Bybit, OKX, Kraken
Public Data only, kein API Key nötig
"""

import ccxt
import pandas as pd
import time
from typing import Optional, Dict, List

class ExchangeConnector:
    def __init__(self):
        # 5 größte nach Volumen
        self.exchanges = {}
        try:
            self.exchanges['binance'] = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
        except: pass
        try:
            self.exchanges['coinbase'] = ccxt.coinbase({'enableRateLimit': True})
        except: pass
        try:
            self.exchanges['bybit'] = ccxt.bybit({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
        except: pass
        try:
            self.exchanges['okx'] = ccxt.okx({'enableRateLimit': True})
        except: pass
        try:
            self.exchanges['kraken'] = ccxt.kraken({'enableRateLimit': True})
        except: pass

        print(f"[Connector] {len(self.exchanges)} Börsen aktiv: {list(self.exchanges.keys())}")

    def normalize_symbol(self, symbol: str, exchange_id: str) -> List[str]:
        """Versuche verschiedene Schreibweisen: WIFUSDT -> WIF/USDT, WIF/USD, WIF-USDT"""
        tries = []
        base = symbol.replace('USDT','').replace('USD','').replace('/','').replace('-','')
        # Original
        tries.append(symbol)
        # Mit Slash
        if 'USDT' in symbol:
            tries.append(f"{base}/USDT")
            tries.append(f"{base}/USD")
        elif '/' not in symbol:
            tries.append(f"{symbol}/USDT")
        # Für Coinbase oft USD statt USDT
        if exchange_id == 'coinbase':
            tries.append(f"{base}/USD")
            tries.append(f"{base}-USD")
        # Unique
        seen = []
        for t in tries:
            if t not in seen:
                seen.append(t)
        return seen

    def fetch_ticker_safe(self, symbol: str) -> Dict[str, Dict]:
        """Holt Ticker von allen 5 Börsen, returned dict exchange->ticker"""
        result = {}
        for eid, ex in self.exchanges.items():
            for try_sym in self.normalize_symbol(symbol, eid):
                try:
                    ticker = ex.fetch_ticker(try_sym)
                    if ticker and ticker.get('last') is not None:
                        result[eid] = ticker
                        break
                except Exception as e:
                    # print(f"{eid} {try_sym} fail {e}")
                    continue
            # small delay to respect rate limit
            time.sleep(ex.rateLimit/1000 if hasattr(ex,'rateLimit') else 0.1)
        return result

    def fetch_ohlcv_safe(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> Optional[pd.DataFrame]:
        """Holt OHLCV von erster Börse die liefert, als DataFrame"""
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
                except Exception as e:
                    continue
            time.sleep(0.1)
        return None

    def fetch_ohlcv_multi(self, symbol: str, timeframe: str, limit: int) -> Dict[str, pd.DataFrame]:
        """Holt OHLCV von ALLEN Börsen die es haben, für MoneyFlow Volumen-Vergleich"""
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
        """Funding für Perps, negativ = viele Shorts = Squeeze Gefahr"""
        for eid in ['bybit','binance','okx']:
            ex = self.exchanges.get(eid)
            if not ex: continue
            for try_sym in self.normalize_symbol(symbol, eid):
                try:
                    # Perps Symbol oft ohne Slash: WIFUSDT
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

# Global singleton für V3.4
connector = ExchangeConnector()
