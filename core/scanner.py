"""
core/scanner.py — Dynamic Pair Scanner for Arunabha Hybrid Bot v1.0
Layer 1: Top gainers | Layer 2: CoinGecko trending | Layer 3: Volume anomaly | Layer 4: Core fixed
"""

import asyncio
import logging
from typing import Optional

import config
from data.binance_client import binance
from data.coingecko_client import coingecko
from data.cache_manager import cache

logger = logging.getLogger(__name__)


class PairScanner:

    def __init__(self):
        self._core_pairs: list[str] = list(config.CORE_PAIRS)
        self._gainer_pairs: list[dict] = []
        self._trending_pairs: list[str] = []
        self._anomaly_pairs: list[str] = []
        self._manual_add: list[str] = []
        self._manual_block: set[str] = set()
        self._manual_remove: set[str] = set()
        self._news_flagged: set[str] = set()
        self._market_caps: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def on_volume_anomaly(self, symbol: str, multiplier: float) -> None:
        if symbol not in self._anomaly_pairs and symbol not in self._manual_block:
            self._anomaly_pairs.append(symbol)
            logger.info(f"⚡ Volume anomaly added: {symbol} ({multiplier:.1f}x)")
        if len(self._anomaly_pairs) > 5:
            self._anomaly_pairs = self._anomaly_pairs[-5:]

    def add_manual_pair(self, symbol: str) -> None:
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        if sym not in self._manual_add:
            self._manual_add.append(sym)

    def remove_pair(self, symbol: str) -> None:
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        self._manual_remove.add(sym)
        if sym in self._manual_add:
            self._manual_add.remove(sym)

    def block_pair(self, symbol: str) -> None:
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        self._manual_block.add(sym)

    def flag_news(self, symbol: str) -> None:
        sym = symbol.upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        self._news_flagged.add(sym)

    def is_news_flagged(self, symbol: str) -> bool:
        return symbol.upper() in self._news_flagged

    async def refresh_market_caps(self) -> None:
        try:
            self._market_caps = await coingecko.get_market_caps()
        except Exception as exc:
            logger.warning(f"Market cap refresh failed: {exc}")

    async def refresh_trending(self) -> None:
        try:
            trending = await coingecko.get_trending_coins()
            valid_symbols = set(await binance.get_usdt_perp_symbols())
            self._trending_pairs = []
            for coin in trending:
                sym = coin["symbol"] + "USDT"
                if sym in valid_symbols:
                    self._trending_pairs.append(sym)
                    if len(self._trending_pairs) >= config.MAX_TRENDING_PAIRS:
                        break
            logger.info(f"Trending pairs updated: {self._trending_pairs}")
        except Exception as exc:
            logger.warning(f"Trending refresh failed: {exc}")

    async def refresh_gainers(self) -> None:
        try:
            valid_symbols = set(await binance.get_usdt_perp_symbols())
            invalid_core = [p for p in self._core_pairs if p not in valid_symbols]
            if invalid_core:
                logger.warning(f"Core pairs not on Binance futures: {invalid_core}")
            self._gainer_pairs = await binance.get_top_gainers(
                self._market_caps, top_n=config.MAX_GAINER_PAIRS
            )
            logger.info(f"Gainer pairs updated: {[g['symbol'] for g in self._gainer_pairs]}")
        except Exception as exc:
            logger.warning(f"Gainer refresh failed: {exc}")

    async def get_active_pairs(self) -> list[str]:
        async with self._lock:
            seen: set[str] = set()
            result: list[str] = []

            def add(sym: str) -> None:
                s = sym.upper()
                if s in self._manual_block or s in self._manual_remove:
                    return
                if s not in seen:
                    seen.add(s)
                    result.append(s)

            for s in self._core_pairs:
                add(s)
            for g in self._gainer_pairs:
                add(g["symbol"])
            for s in self._trending_pairs:
                add(s)
            for s in self._anomaly_pairs:
                add(s)
            for s in self._manual_add:
                add(s)

            return result[:config.MAX_TOTAL_PAIRS]

    def get_gainer_info(self, symbol: str) -> Optional[dict]:
        for g in self._gainer_pairs:
            if g["symbol"] == symbol:
                return g
        return None

    def get_trending_rank(self, symbol: str) -> Optional[int]:
        for i, s in enumerate(self._trending_pairs):
            if s == symbol:
                return i + 1
        return None

    def is_anomaly(self, symbol: str) -> bool:
        return symbol.upper() in self._anomaly_pairs

    def get_status(self) -> dict:
        return {
            "core": self._core_pairs,
            "gainers": [g["symbol"] for g in self._gainer_pairs],
            "trending": self._trending_pairs,
            "anomaly": self._anomaly_pairs,
            "manual_add": self._manual_add,
            "blocked": list(self._manual_block),
            "news_flagged": list(self._news_flagged),
        }


scanner = PairScanner()
