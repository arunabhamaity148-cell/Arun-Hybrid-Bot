"""
data/coindcx_client.py — CoinDCX price reference client. Read-only. No trading.
"""

import logging
import aiohttp
from typing import Optional

from data.cache_manager import cache
import config

logger = logging.getLogger(__name__)
COINDCX_BASE = "https://api.coindcx.com"


class CoinDCXClient:

    async def get_ticker(self, symbol: str) -> Optional[dict]:
        cache_key = f"coindcx_ticker:{symbol}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                async with session.get(f"{COINDCX_BASE}/exchange/ticker") as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    target = f"B-{symbol[:-4]}_{symbol[-4:]}" if symbol.endswith("USDT") else symbol
                    for item in data:
                        if item.get("market") == target:
                            await cache.set(cache_key, item, ttl=30.0)
                            return item
        except Exception as exc:
            logger.debug(f"CoinDCX ticker fetch failed for {symbol}: {exc}")
        return None

    async def get_all_tickers(self) -> list[dict]:
        cached = await cache.get("coindcx_all_tickers")
        if cached is not None:
            return cached
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(f"{COINDCX_BASE}/exchange/ticker") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        await cache.set("coindcx_all_tickers", data, ttl=60.0)
                        return data
        except Exception as exc:
            logger.debug(f"CoinDCX all tickers failed: {exc}")
        return []


coindcx = CoinDCXClient()
