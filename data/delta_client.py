"""
data/delta_client.py — Delta Exchange READ-ONLY price reference.
⚠️ STRICTLY READ-ONLY — NO order placement, NO trading functions.
"""

import logging
import aiohttp
import hashlib
import hmac
import time
from typing import Optional

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)
DELTA_BASE = "https://api.delta.exchange"


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

        path = f"/v2/tickers/{symbol}"
        headers = self._sign("GET", path)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
                async with session.get(f"{DELTA_BASE}{path}", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        result = data.get("result", {})
                        await cache.set(cache_key, result, ttl=15.0)
                        return result
        except Exception as exc:
            logger.debug(f"Delta ticker fetch failed for {symbol}: {exc}")
        return None

    async def get_all_products(self) -> list[dict]:
        cached = await cache.get("delta_products")
        if cached is not None:
            return cached
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
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
