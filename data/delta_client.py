"""
data/delta_client.py — Delta Exchange READ-ONLY client
⚠️ STRICTLY READ-ONLY — NO order placement, NO trading functions.

Priority 2 Update:
  get_klines() added — Delta এর নিজস্ব OHLCV candle data
  Symbol mapping: ZECUSDT → ZECUSD (Delta format)
  Fallback: Delta fail হলে Binance থেকে নেবে (zero downtime)
"""

import logging
import aiohttp
import hashlib
import hmac
import time
import pandas as pd
from typing import Optional

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)
DELTA_BASE = "https://api.delta.exchange"

# Binance USDT → Delta USD symbol mapping
# Delta perpetuals use USD, not USDT
DELTA_SYMBOL_MAP = {
    "BTCUSDT":  "BTCUSD",
    "ETHUSDT":  "ETHUSD",
    "SOLUSDT":  "SOLUSD",
    "BNBUSDT":  "BNBUSD",
    "DOGEUSDT": "DOGEUSD",
    "ZECUSDT":  "ZECUSD",
    "XRPUSDT":  "XRPUSD",
    "ADAUSDT":  "ADAUSD",
    "DOTUSDT":  "DOTUSD",
    "AVAXUSDT": "AVAXUSD",
    "LINKUSDT": "LINKUSD",
    "MATICUSDT":"MATICUSD",
    "PEPEUSDT": "PEPEUSD",
    "SHIBUSDT": "SHIBUSD",
}

# Interval → Delta resolution (minutes)
INTERVAL_MAP = {
    "1m":  1,
    "5m":  5,
    "15m": 15,
    "30m": 30,
    "1h":  60,
    "4h":  240,
    "1d":  1440,
}


def to_delta_symbol(binance_symbol: str) -> str:
    """ZECUSDT → ZECUSD"""
    if binance_symbol in DELTA_SYMBOL_MAP:
        return DELTA_SYMBOL_MAP[binance_symbol]
    # Fallback: replace USDT with USD
    return binance_symbol.replace("USDT", "USD").replace("BUSD", "USD")


class DeltaClient:
    """Price-feed-only client. Zero order/position endpoints."""

    def _sign(self, method: str, path: str, body: str = "") -> dict:
        timestamp = str(int(time.time()))
        signature_data = method + timestamp + path + body
        signature = hmac.new(
            config.DELTA_SECRET.encode(),
            signature_data.encode(),
            hashlib.sha256,
        ).hexdigest()
        return {
            "api-key": config.DELTA_API_KEY,
            "timestamp": timestamp,
            "signature": signature,
            "Content-Type": "application/json",
        }

    async def get_ticker(self, symbol: str) -> Optional[dict]:
        cache_key = f"delta_ticker:{symbol}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

        if not config.DELTA_API_KEY:
            return None

        delta_sym = to_delta_symbol(symbol)
        path = f"/v2/tickers/{delta_sym}"
        headers = self._sign("GET", path)
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=8)
            ) as session:
                async with session.get(
                    f"{DELTA_BASE}{path}", headers=headers
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        await cache.set(cache_key, result, ttl=15.0)
                        return result
        except Exception as exc:
            logger.debug(f"Delta ticker fetch failed for {symbol}: {exc}")
        return None

    async def get_klines(
        self,
        symbol: str,
        interval: str = "15m",
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        Delta Exchange থেকে OHLCV candle data fetch করো।
        Returns pd.DataFrame with columns: open, high, low, close, volume
        Returns empty DataFrame on failure (caller falls back to Binance).

        No API key needed — public endpoint.
        """
        cache_key = f"delta_klines:{symbol}:{interval}:{limit}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

        delta_sym = to_delta_symbol(symbol)
        resolution = INTERVAL_MAP.get(interval, 15)

        end_time = int(time.time())
        start_time = end_time - (limit * resolution * 60) - (resolution * 60)

        params = {
            "symbol":     delta_sym,
            "resolution": resolution,
            "start":      start_time,
            "end":        end_time,
        }

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.get(
                    f"{DELTA_BASE}/v2/history/candles", params=params
                ) as resp:
                    if resp.status != 200:
                        logger.debug(
                            f"Delta klines HTTP {resp.status} for {delta_sym}"
                        )
                        return pd.DataFrame()

                    data = await resp.json()
                    candles = data.get("result", [])

                    if not candles:
                        return pd.DataFrame()

                    # Delta returns: {time, open, high, low, close, volume}
                    df = pd.DataFrame(candles)
                    df = df.rename(columns={
                        "time":   "timestamp",
                        "open":   "open",
                        "high":   "high",
                        "low":    "low",
                        "close":  "close",
                        "volume": "volume",
                    })

                    for col in ["open", "high", "low", "close", "volume"]:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                    df = df.sort_values("timestamp").reset_index(drop=True)
                    df = df.tail(limit).reset_index(drop=True)

                    # Cache 30 seconds (candles don't change rapidly)
                    await cache.set(cache_key, df, ttl=30.0)
                    logger.debug(
                        f"Delta klines: {delta_sym} {interval} → {len(df)} candles"
                    )
                    return df

        except Exception as exc:
            logger.debug(f"Delta klines fetch failed for {symbol}: {exc}")
            return pd.DataFrame()

    async def get_mark_price(self, symbol: str) -> Optional[float]:
        """
        Delta এর mark price fetch — signal engine এ current_price হিসেবে ব্যবহার করো।
        এটা Binance last price এর চেয়ে Delta trade এর জন্য বেশি accurate।
        """
        ticker = await self.get_ticker(symbol)
        if ticker:
            mark = ticker.get("mark_price") or ticker.get("last_price")
            if mark:
                return float(mark)
        return None

    async def get_all_products(self) -> list[dict]:
        cached = await cache.get("delta_products")
        if cached is not None:
            return cached
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.get(
                    f"{DELTA_BASE}/v2/products",
                    params={"contract_type": "perpetual_futures"},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        products = data.get("result", [])
                        await cache.set("delta_products", products, ttl=3600.0)
                        return products
        except Exception as exc:
            logger.debug(f"Delta products fetch failed: {exc}")
        return []


delta = DeltaClient()
