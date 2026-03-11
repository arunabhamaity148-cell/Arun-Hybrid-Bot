"""
data/binance_client.py — Binance REST + WebSocket client for Arunabha Hybrid Bot v1.0
Endpoint rotation, auto-reconnect WebSocket, volume anomaly detection.
NO order placement — read-only data source.
"""

import asyncio
import json
import logging
import time
import random
from typing import Optional, Callable, Any
import aiohttp
import pandas as pd
import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

_endpoint_index = 0
_endpoint_lock = asyncio.Lock()


async def _get_base_url() -> str:
    global _endpoint_index
    async with _endpoint_lock:
        url = config.BINANCE_REST_ENDPOINTS[_endpoint_index % len(config.BINANCE_REST_ENDPOINTS)]
        _endpoint_index += 1
        return url


async def _get(path: str, params: Optional[dict] = None, retries: int = 3) -> Any:
    last_exc = None
    for attempt in range(retries):
        base = await _get_base_url()
        url = f"{base}{path}"
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
                connector=aiohttp.TCPConnector(ssl=False),
            ) as session:
                async with session.get(url, params=params) as resp:
                    if resp.status == 429:
                        wait = 2 ** attempt
                        logger.warning(f"Binance rate-limit on {base} — sleeping {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as exc:
            last_exc = exc
            logger.warning(f"Binance REST attempt {attempt+1}/{retries} failed: {exc}")
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Binance REST failed after {retries} attempts: {last_exc}")


class BinanceClient:
    """All Binance data fetching. NEVER places orders."""

    async def get_klines(self, symbol: str, interval: str, limit: int = 200, use_cache: bool = True) -> pd.DataFrame:
        cache_key = f"klines:{symbol}:{interval}:{limit}"
        if use_cache:
            cached = await cache.get(cache_key)
            if cached is not None:
                return cached

        data = await _get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit})
        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(
            data,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ],
        )
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = df[col].astype(float)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        df.set_index("open_time", inplace=True)

        ttl = 60.0 if interval in ("1m", "3m", "5m") else 300.0
        await cache.set(cache_key, df, ttl=ttl)
        return df

    async def get_24h_tickers(self) -> list[dict]:
        cached = await cache.get("24h_tickers")
        if cached is not None:
            return cached
        data = await _get("/fapi/v1/ticker/24hr")
        await cache.set("24h_tickers", data, ttl=60.0)
        return data

    async def get_usdt_perp_symbols(self) -> list[str]:
        cached = await cache.get("usdt_perp_symbols")
        if cached is not None:
            return cached
        data = await _get("/fapi/v1/exchangeInfo")
        symbols = [
            s["symbol"]
            for s in data.get("symbols", [])
            if s["quoteAsset"] == "USDT"
            and s["status"] == "TRADING"
            and s["contractType"] == "PERPETUAL"
        ]
        await cache.set("usdt_perp_symbols", symbols, ttl=3600.0)
        return symbols

    async def get_price(self, symbol: str) -> float:
        cache_key = f"price:{symbol}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached
        data = await _get("/fapi/v1/ticker/price", {"symbol": symbol})
        price = float(data["price"])
        await cache.set(cache_key, price, ttl=5.0)
        return price

    async def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        cache_key = f"orderbook:{symbol}:{limit}"
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached
        data = await _get("/fapi/v1/depth", {"symbol": symbol, "limit": limit})
        await cache.set(cache_key, data, ttl=5.0)
        return data

    async def get_top_gainers(self, market_caps: dict[str, float], top_n: int = 5) -> list[dict]:
        tickers = await self.get_24h_tickers()
        valid_symbols = set(await self.get_usdt_perp_symbols())

        results = []
        for t in tickers:
            sym = t.get("symbol", "")
            if sym not in valid_symbols:
                continue
            price = float(t.get("lastPrice", 0))
            change_pct = float(t.get("priceChangePercent", 0))
            volume_usd = float(t.get("quoteVolume", 0))

            if price < config.MIN_PRICE_USD:
                continue
            if change_pct < config.MIN_24H_CHANGE_PCT:
                continue

            base = sym.replace("USDT", "").replace("BUSD", "").lower()
            mcap = market_caps.get(base, 0)
            if mcap < config.MIN_MARKET_CAP_USD:
                continue

            results.append({"symbol": sym, "price": price, "change_pct": change_pct, "volume_usd": volume_usd})

        filtered = []
        for r in sorted(results, key=lambda x: x["change_pct"], reverse=True)[:20]:
            try:
                df = await self.get_klines(r["symbol"], "1d", limit=21)
                if len(df) < 21:
                    continue
                avg_vol = df["volume"].iloc[:-1].mean()
                today_vol = df["volume"].iloc[-1]
                vol_mult = today_vol / avg_vol if avg_vol > 0 else 0
                if vol_mult >= config.MIN_VOLUME_MULTIPLIER:
                    r["vol_multiplier"] = round(vol_mult, 2)
                    filtered.append(r)
            except Exception as exc:
                logger.debug(f"Volume check failed for {r['symbol']}: {exc}")

        return filtered[:top_n]

    async def check_new_futures_listings(self) -> list[str]:
        try:
            data = await _get("/fapi/v1/exchangeInfo")
            new = []
            now_ms = int(time.time() * 1000)
            seven_days_ms = 7 * 24 * 3600 * 1000
            for s in data.get("symbols", []):
                onboard = s.get("onboardDate", 0)
                if onboard and (now_ms - onboard) < seven_days_ms:
                    if s.get("contractType") == "PERPETUAL":
                        new.append(s["symbol"])
            return new
        except Exception as exc:
            logger.warning(f"New listings check failed: {exc}")
            return []


class VolumeAnomalyWatcher:

    def __init__(self, on_anomaly: Callable[[str, float], None]):
        self._on_anomaly = on_anomaly
        self._buckets: dict[str, list[float]] = {}
        self._running = False
        self._ws_url_index = 0
        self._subscribed_symbols: set[str] = set()

    def set_symbols(self, symbols: list[str]) -> None:
        self._subscribed_symbols = set(s.lower() for s in symbols)

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._ws_loop())

    async def stop(self) -> None:
        self._running = False

    async def _ws_loop(self) -> None:
        reconnect_delay = config.WS_RECONNECT_BASE_DELAY
        attempt = 0

        while self._running:
            ws_base = config.BINANCE_WS_ENDPOINTS[self._ws_url_index % len(config.BINANCE_WS_ENDPOINTS)]
            self._ws_url_index += 1

            symbols = list(self._subscribed_symbols)
            if not symbols:
                await asyncio.sleep(5)
                continue

            streams = "/".join(f"{s}@kline_1m" for s in symbols[:40])
            url = f"{ws_base}/stream?streams={streams}"

            try:
                logger.info(f"VolumeAnomalyWatcher: connecting to {ws_base} (attempt {attempt+1})")
                async with websockets.connect(
                    url,
                    ping_interval=config.WS_HEARTBEAT_INTERVAL,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    reconnect_delay = config.WS_RECONNECT_BASE_DELAY
                    attempt = 0
                    logger.info("VolumeAnomalyWatcher: WebSocket connected ✓")

                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                            data = msg.get("data", {})
                            if data.get("e") == "kline":
                                await self._process_kline(data)
                        except Exception as exc:
                            logger.debug(f"WS message parse error: {exc}")

            except (ConnectionClosed, WebSocketException, OSError) as exc:
                attempt += 1
                reconnect_delay = min(reconnect_delay * 2, 60)
                logger.warning(f"VolumeAnomalyWatcher WS disconnected: {exc}. Reconnect in {reconnect_delay:.1f}s")
                if attempt >= config.WS_MAX_RECONNECT_ATTEMPTS:
                    logger.error("VolumeAnomalyWatcher: max reconnect attempts reached — resetting counter")
                    attempt = 0
                await asyncio.sleep(reconnect_delay)
            except Exception as exc:
                logger.error(f"VolumeAnomalyWatcher unexpected error: {exc}", exc_info=True)
                await asyncio.sleep(5)

    async def _process_kline(self, kline_data: dict) -> None:
        symbol = kline_data["s"].upper()
        k = kline_data["k"]
        if not k.get("x", False):
            return
        volume = float(k["v"])
        bucket = self._buckets.setdefault(symbol, [])
        bucket.append(volume)
        if len(bucket) > 30:
            self._buckets[symbol] = bucket[-30:]
        await self._check_anomaly(symbol)

    async def _check_anomaly(self, symbol: str) -> None:
        bucket = self._buckets.get(symbol, [])
        if len(bucket) < 30:
            return
        current_window = sum(bucket[-15:])
        prev_window = sum(bucket[:15])
        if prev_window == 0:
            return
        multiplier = current_window / prev_window
        if multiplier >= config.VOLUME_ANOMALY_MULTIPLIER:
            logger.info(f"⚡ VOLUME ANOMALY: {symbol} — {multiplier:.1f}x spike")
            self._on_anomaly(symbol, multiplier)


binance = BinanceClient()
