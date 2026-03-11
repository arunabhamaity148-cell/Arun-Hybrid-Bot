"""
data/coingecko_client.py — CoinGecko free-tier client for Arunabha Hybrid Bot v1.0
Trending coins, market cap data, Fear & Greed index, new listings.
"""

import asyncio
import logging
import time
import aiohttp
from typing import Optional

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
FEAR_GREED_URL = "https://api.alternative.me/fng/?limit=1"

_request_times: list[float] = []
_rate_lock = asyncio.Lock()


async def _rate_limited_get(url: str, params: Optional[dict] = None) -> dict:
    async with _rate_lock:
        now = time.monotonic()
        _request_times[:] = [t for t in _request_times if now - t < 60]
        if len(_request_times) >= 45:
            sleep_time = 60 - (now - _request_times[0]) + 0.5
            logger.debug(f"CoinGecko rate limit: sleeping {sleep_time:.1f}s")
            await asyncio.sleep(sleep_time)
        _request_times.append(time.monotonic())

    headers = {}
    if config.COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(url, params=params, headers=headers) as resp:
                    if resp.status == 429:
                        wait = 30 * (attempt + 1)
                        logger.warning(f"CoinGecko 429 — sleeping {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning(f"CoinGecko HTTP {resp.status} for {url}")
                    return {}
        except Exception as exc:
            logger.warning(f"CoinGecko request attempt {attempt+1} failed: {exc}")
            await asyncio.sleep(3 * (attempt + 1))
    return {}


class CoinGeckoClient:

    async def get_trending_coins(self) -> list[dict]:
        cached = await cache.get("cg_trending")
        if cached is not None:
            return cached

        data = await _rate_limited_get(f"{COINGECKO_BASE}/search/trending")
        coins = []
        for item in data.get("coins", []):
            coin = item.get("item", {})
            coins.append({
                "symbol": coin.get("symbol", "").upper(),
                "name": coin.get("name", ""),
                "market_cap_rank": coin.get("market_cap_rank"),
                "score": coin.get("score", 0),
            })
        await cache.set("cg_trending", coins, ttl=config.COINGECKO_REFRESH_SECONDS)
        logger.info(f"CoinGecko: fetched {len(coins)} trending coins")
        return coins

    async def get_market_caps(self, symbols: Optional[list[str]] = None) -> dict[str, float]:
        cached = await cache.get("cg_market_caps")
        if cached is not None:
            return cached

        mcaps: dict[str, float] = {}
        for page in range(1, 6):
            data = await _rate_limited_get(
                f"{COINGECKO_BASE}/coins/markets",
                {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 100, "page": page, "sparkline": "false"},
            )
            if not data:
                break
            for coin in data:
                sym = coin.get("symbol", "").lower()
                mcap = coin.get("market_cap") or 0
                mcaps[sym] = float(mcap)
            await asyncio.sleep(0.5)

        await cache.set("cg_market_caps", mcaps, ttl=3600.0)
        logger.info(f"CoinGecko: loaded market caps for {len(mcaps)} coins")
        return mcaps

    async def get_fear_greed(self) -> dict:
        cached = await cache.get("fear_greed")
        if cached is not None:
            return cached

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                async with session.get(FEAR_GREED_URL) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        entry = data.get("data", [{}])[0]
                        result = {
                            "value": int(entry.get("value", 50)),
                            "value_classification": entry.get("value_classification", "Neutral"),
                        }
                        await cache.set("fear_greed", result, ttl=3600.0)
                        return result
        except Exception as exc:
            logger.warning(f"Fear & Greed fetch failed: {exc}")

        return {"value": 50, "value_classification": "Neutral"}

    async def get_new_listings(self) -> list[dict]:
        cached = await cache.get("cg_new_listings")
        if cached is not None:
            return cached

        data = await _rate_limited_get(f"{COINGECKO_BASE}/coins/list/new")
        result = []
        for coin in (data if isinstance(data, list) else []):
            result.append({
                "id": coin.get("id"),
                "symbol": coin.get("symbol", "").upper(),
                "name": coin.get("name"),
                "activated_at": coin.get("activated_at"),
            })
        await cache.set("cg_new_listings", result, ttl=3600.0)
        return result


coingecko = CoinGeckoClient()
