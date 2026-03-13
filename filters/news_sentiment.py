"""
filters/news_sentiment.py — Filter F0: News Sentiment Check

CryptoPanic API (free tier) থেকে last 24h এর major news check করে।
Bullish news থাকলে SHORT block, Bearish news থাকলে LONG block।

Free tier limits:
  - 5 requests/minute
  - Public endpoint (no auth key needed for basic use)
  - Auth token দিলে more fields পাওয়া যায়

Logic:
  Sentiment score গণনা করা হয় votes থেকে:
    bullish_score  = sum of (liked - disliked) for bullish news
    bearish_score  = sum of (liked - disliked) for bearish news

  যদি bullish_score - bearish_score > threshold → LONG bias
    → SHORT signal block (market bullish momentum এ)
  যদি bearish_score - bullish_score > threshold → BEARISH bias
    → LONG signal block (market bearish momentum এ)
  যদি neutral → উভয় allow

  Coin-specific news:
    symbol e.g. SOLUSDT → SOL এর specific news দেখো
    BTC/ETH এর major news সব coin কে affect করে

Config:
  NEWS_SENTIMENT_ENABLED: True/False
  NEWS_SENTIMENT_THRESHOLD: কতটা sentiment gap হলে block (default 3)
  NEWS_CRYPTOPANIC_TOKEN: optional, free account থেকে পাওয়া যায়
  NEWS_CACHE_MINUTES: কত মিনিট cache রাখবে (default 15)
"""

import logging
import time
from typing import Tuple, Optional

import aiohttp
import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1/posts/"


def _coin_symbol(symbol: str) -> str:
    """SOLUSDT → SOL"""
    return symbol.replace("USDT", "").replace("BUSD", "").replace("USDC", "")


async def _fetch_news(currencies: str) -> list[dict]:
    """
    Fetch recent news from CryptoPanic for given currencies.
    currencies: comma-separated e.g. "BTC,SOL"
    Returns list of post dicts or [] on error.
    """
    params = {
        "filter": "hot",
        "public": "true",
        "currencies": currencies,
        "kind": "news",
    }
    if config.NEWS_CRYPTOPANIC_TOKEN:
        params["auth_token"] = config.NEWS_CRYPTOPANIC_TOKEN

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=6)
        ) as sess:
            async with sess.get(CRYPTOPANIC_BASE, params=params) as resp:
                if resp.status != 200:
                    logger.debug(f"CryptoPanic returned {resp.status}")
                    return []
                data = await resp.json()
                return data.get("results", [])
    except Exception as exc:
        logger.debug(f"CryptoPanic fetch error: {exc}")
        return []


def _score_posts(posts: list[dict]) -> Tuple[float, float, list[str]]:
    """
    Score posts as bullish/bearish based on votes and labels.
    Returns (bullish_score, bearish_score, important_headlines).

    CryptoPanic post structure:
      votes: {liked, disliked, important, lol, toxic, saved}
      currencies: [{code, title}]
      title: str
      is_hot: bool
    """
    bullish_score = 0.0
    bearish_score = 0.0
    headlines = []

    now = time.time()

    for post in posts:
        title = post.get("title", "")
        votes = post.get("votes", {})
        liked = votes.get("liked", 0) or 0
        disliked = votes.get("disliked", 0) or 0
        important = votes.get("important", 0) or 0
        is_hot = post.get("is_hot", False)

        # Weight: important/hot posts count more
        weight = 1.0
        if important > 2:
            weight = 1.5
        if is_hot:
            weight = 2.0

        net_votes = (liked - disliked) * weight

        # Keyword-based sentiment detection
        title_lower = title.lower()

        bullish_keywords = [
            "surge", "rally", "pump", "breakout", "bullish", "adopt",
            "partnership", "launch", "upgrade", "all-time high", "ath",
            "etf approved", "listing", "integration", "milestone",
        ]
        bearish_keywords = [
            "crash", "dump", "bearish", "ban", "hack", "exploit",
            "lawsuit", "sec", "regulation", "collapse", "fraud",
            "rug", "scam", "delisting", "warning", "investigation",
        ]

        is_bullish = any(kw in title_lower for kw in bullish_keywords)
        is_bearish = any(kw in title_lower for kw in bearish_keywords)

        if is_bullish and not is_bearish:
            bullish_score += max(net_votes, weight)
            if net_votes > 2 or is_hot:
                headlines.append(f"📈 {title[:60]}")
        elif is_bearish and not is_bullish:
            bearish_score += max(net_votes, weight)
            if net_votes > 2 or is_hot:
                headlines.append(f"📉 {title[:60]}")

    return bullish_score, bearish_score, headlines[:3]


async def check_news_sentiment(
    symbol: str,
    direction: str,
) -> Tuple[bool, str]:
    """
    Returns (passed, log_message).

    LONG direction → blocked if strong bearish news
    SHORT direction → blocked if strong bullish news
    Neutral or fetch error → always passes
    """
    if not config.NEWS_SENTIMENT_ENABLED:
        return True, "NEWS: disabled — skipping ✅"

    coin = _coin_symbol(symbol)

    # Cache key — cache per coin, 15 minutes
    cache_key = f"news_sentiment:{coin}"
    cached = await cache.get(cache_key)
    if cached is not None:
        bull, bear, headlines, label = cached
    else:
        # Fetch coin-specific + BTC general (BTC news affects all)
        currencies = coin if coin == "BTC" else f"{coin},BTC"
        posts = await _fetch_news(currencies)

        if not posts:
            # API fail or empty → allow, don't block signal
            return True, f"NEWS: No data from CryptoPanic — allowing ✅"

        bull, bear, headlines = _score_posts(posts)

        net = bull - bear
        if net > config.NEWS_SENTIMENT_THRESHOLD:
            label = "BULLISH"
        elif bear - bull > config.NEWS_SENTIMENT_THRESHOLD:
            label = "BEARISH"
        else:
            label = "NEUTRAL"

        await cache.set(
            cache_key,
            (bull, bear, headlines, label),
            ttl=config.NEWS_CACHE_MINUTES * 60
        )

    net = bull - bear
    headline_str = " | ".join(headlines) if headlines else "no major news"

    if label == "BULLISH" and direction == "SHORT":
        msg = (
            f"NEWS: BULLISH sentiment (score +{bull:.0f}) — "
            f"SHORT blocked ❌ | {headline_str}"
        )
        return False, msg

    elif label == "BEARISH" and direction == "LONG":
        msg = (
            f"NEWS: BEARISH sentiment (score -{bear:.0f}) — "
            f"LONG blocked ❌ | {headline_str}"
        )
        return False, msg

    elif label == "BULLISH":
        msg = f"NEWS: BULLISH (+{bull:.0f}) — LONG aligns ✅ | {headline_str}"
        return True, msg

    elif label == "BEARISH":
        msg = f"NEWS: BEARISH (-{bear:.0f}) — SHORT aligns ✅ | {headline_str}"
        return True, msg

    else:
        msg = f"NEWS: NEUTRAL (bull:{bull:.0f} bear:{bear:.0f}) — no block ✅"
        return True, msg
