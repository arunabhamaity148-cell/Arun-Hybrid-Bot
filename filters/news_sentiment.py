"""
filters/news_sentiment.py — Filter F0: News Sentiment Check

Multiple free sources থেকে last 24h এর major news check করে।
Bullish news থাকলে SHORT block, Bearish news থাকলে LONG block।

Sources (সবই সম্পূর্ণ FREE, কোনো API key লাগে না):
  1. CryptoPanic  — hot crypto news + votes
  2. CoinGecko    — price sentiment % (bullish/bearish community votes)
  3. CoinDesk RSS — major news headlines
  4. Fear & Greed — overall market mood (0-100)

Combined Sentiment Score Logic:
  প্রতিটা source এর score আলাদা করে বের করা হয়
  তারপর weighted average করা হয়:
    CryptoPanic  → 35%
    CoinGecko    → 25%
    CoinDesk     → 20%
    Fear & Greed → 20%

  Final score > threshold → BULLISH → SHORT block
  Final score < -threshold → BEARISH → LONG block
  Otherwise → NEUTRAL → উভয় allow

Config:
  NEWS_SENTIMENT_ENABLED: True/False
  NEWS_SENTIMENT_THRESHOLD: কতটা gap হলে block (default 3)
  NEWS_CRYPTOPANIC_TOKEN: optional free token
  NEWS_CACHE_MINUTES: cache duration (default 15)
"""

import logging
import time
import xml.etree.ElementTree as ET
from typing import Tuple

import aiohttp
import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

# ── API Endpoints ────────────────────────────────────────────────────────────
CRYPTOPANIC_BASE  = "https://cryptopanic.com/api/v1/posts/"
COINGECKO_BASE    = "https://api.coingecko.com/api/v3/coins/{coin_id}"
COINDESK_RSS      = "https://feeds.feedburner.com/CoinDesk"
FEAR_GREED_API    = "https://api.alternative.me/fng/?limit=1"

# CoinGecko coin id map (symbol → coingecko id)
COINGECKO_IDS = {
    "BTC":  "bitcoin",
    "ETH":  "ethereum",
    "SOL":  "solana",
    "ZEC":  "zcash",
    "BNB":  "binancecoin",
    "XRP":  "ripple",
    "ADA":  "cardano",
    "DOGE": "dogecoin",
    "DOT":  "polkadot",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "MATIC":"matic-network",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _coin_symbol(symbol: str) -> str:
    """SOLUSDT → SOL"""
    for suffix in ("USDT", "BUSD", "USDC", "PERP"):
        symbol = symbol.replace(suffix, "")
    return symbol.upper()


# ── Source 1: CryptoPanic ────────────────────────────────────────────────────

async def _fetch_cryptopanic(coin: str) -> Tuple[float, float, list[str]]:
    """
    CryptoPanic থেকে news fetch করে।
    Returns (bullish_score, bearish_score, headlines)
    No API key needed for basic public access.
    """
    params = {
        "filter": "hot",
        "public": "true",
        "currencies": coin if coin == "BTC" else f"{coin},BTC",
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
                    return 0.0, 0.0, []
                data = await resp.json()
                posts = data.get("results", [])
    except Exception as exc:
        logger.debug(f"CryptoPanic error: {exc}")
        return 0.0, 0.0, []

    bullish_keywords = [
        "surge", "rally", "pump", "breakout", "bullish", "adopt",
        "partnership", "launch", "upgrade", "all-time high", "ath",
        "etf approved", "listing", "integration", "milestone", "fund",
    ]
    bearish_keywords = [
        "crash", "dump", "bearish", "ban", "hack", "exploit",
        "lawsuit", "sec", "regulation", "collapse", "fraud",
        "rug", "scam", "delisting", "warning", "investigation",
    ]

    bull, bear = 0.0, 0.0
    headlines = []

    for post in posts:
        title      = post.get("title", "")
        votes      = post.get("votes", {})
        liked      = votes.get("liked", 0) or 0
        disliked   = votes.get("disliked", 0) or 0
        important  = votes.get("important", 0) or 0
        is_hot     = post.get("is_hot", False)

        weight = 2.0 if is_hot else (1.5 if important > 2 else 1.0)
        net    = (liked - disliked) * weight
        t      = title.lower()

        is_bull = any(kw in t for kw in bullish_keywords)
        is_bear = any(kw in t for kw in bearish_keywords)

        if is_bull and not is_bear:
            bull += max(net, weight)
            if net > 2 or is_hot:
                headlines.append(f"📈 {title[:60]}")
        elif is_bear and not is_bull:
            bear += max(net, weight)
            if net > 2 or is_hot:
                headlines.append(f"📉 {title[:60]}")

    return bull, bear, headlines[:3]


# ── Source 2: CoinGecko Sentiment ────────────────────────────────────────────

async def _fetch_coingecko_sentiment(coin: str) -> Tuple[float, float, str]:
    """
    CoinGecko community sentiment percentage fetch করে।
    Returns (bullish_score, bearish_score, info_str)
    No API key needed.
    """
    coin_id = COINGECKO_IDS.get(coin)
    if not coin_id:
        return 0.0, 0.0, "unknown coin"

    url = COINGECKO_BASE.format(coin_id=coin_id)
    params = {"localization": "false", "tickers": "false",
              "market_data": "false", "community_data": "true"}

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=6)
        ) as sess:
            async with sess.get(url, params=params) as resp:
                if resp.status != 200:
                    return 0.0, 0.0, "fetch failed"
                data = await resp.json()
    except Exception as exc:
        logger.debug(f"CoinGecko error: {exc}")
        return 0.0, 0.0, "error"

    bull_pct = data.get("sentiment_votes_up_percentage") or 50.0
    bear_pct = data.get("sentiment_votes_down_percentage") or 50.0

    # Convert percentage to score (0-10 range)
    bull_score = (bull_pct / 100) * 10
    bear_score = (bear_pct / 100) * 10

    info = f"CoinGecko: 🟢{bull_pct:.0f}% bulls / 🔴{bear_pct:.0f}% bears"
    return bull_score, bear_score, info


# ── Source 3: CoinDesk RSS ───────────────────────────────────────────────────

async def _fetch_coindesk_rss(coin: str) -> Tuple[float, float, list[str]]:
    """
    CoinDesk RSS feed থেকে news headlines check করে।
    Returns (bullish_score, bearish_score, headlines)
    No API key needed.
    """
    bullish_keywords = [
        "surge", "rally", "bull", "rise", "gain", "high", "adopt",
        "approve", "launch", "upgrade", "buy", "inflow", "fund",
    ]
    bearish_keywords = [
        "crash", "fall", "drop", "bear", "low", "ban", "hack",
        "lawsuit", "sec", "warning", "sell", "outflow", "fraud",
    ]

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=6)
        ) as sess:
            async with sess.get(COINDESK_RSS) as resp:
                if resp.status != 200:
                    return 0.0, 0.0, []
                text = await resp.text()
    except Exception as exc:
        logger.debug(f"CoinDesk RSS error: {exc}")
        return 0.0, 0.0, []

    bull, bear = 0.0, 0.0
    headlines = []

    try:
        root = ET.fromstring(text)
        items = root.findall(".//item")[:20]  # last 20 news

        for item in items:
            title_el = item.find("title")
            if title_el is None:
                continue
            title = title_el.text or ""
            t     = title.lower()

            # Coin specific বা general crypto news
            coin_mentioned = coin.lower() in t or "bitcoin" in t or "crypto" in t

            if not coin_mentioned:
                continue

            is_bull = any(kw in t for kw in bullish_keywords)
            is_bear = any(kw in t for kw in bearish_keywords)

            if is_bull and not is_bear:
                bull += 1.0
                headlines.append(f"📈 {title[:60]}")
            elif is_bear and not is_bull:
                bear += 1.0
                headlines.append(f"📉 {title[:60]}")

    except ET.ParseError as exc:
        logger.debug(f"CoinDesk RSS parse error: {exc}")

    return bull, bear, headlines[:2]


# ── Source 4: Fear & Greed Index ─────────────────────────────────────────────

async def _fetch_fear_greed() -> Tuple[float, float, str]:
    """
    Alternative.me Fear & Greed Index fetch করে।
    Returns (bullish_score, bearish_score, info_str)
    No API key needed.

    Index: 0-24 = Extreme Fear, 25-49 = Fear,
           50-74 = Greed, 75-100 = Extreme Greed
    """
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as sess:
            async with sess.get(FEAR_GREED_API) as resp:
                if resp.status != 200:
                    return 0.0, 0.0, "F&G: fetch failed"
                data = await resp.json()
                value       = int(data["data"][0]["value"])
                value_class = data["data"][0]["value_classification"]
    except Exception as exc:
        logger.debug(f"Fear & Greed error: {exc}")
        return 0.0, 0.0, "F&G: error"

    # Convert 0-100 to bull/bear score (0-10)
    bull_score = (value / 100) * 10
    bear_score = ((100 - value) / 100) * 10

    emoji = "😨" if value < 25 else "😟" if value < 50 else "😏" if value < 75 else "🤑"
    info  = f"Fear&Greed: {emoji} {value}/100 ({value_class})"

    return bull_score, bear_score, info


# ── Combined Scorer ──────────────────────────────────────────────────────────

async def _get_combined_sentiment(coin: str) -> Tuple[str, float, float, list[str]]:
    """
    চারটা source থেকে weighted combined sentiment বের করে।
    Returns (label, total_bull, total_bear, all_headlines)
    """
    # সব source parallel এ fetch করি
    import asyncio
    cp_task  = _fetch_cryptopanic(coin)
    cg_task  = _fetch_coingecko_sentiment(coin)
    cd_task  = _fetch_coindesk_rss(coin)
    fg_task  = _fetch_fear_greed()

    (cp_bull, cp_bear, cp_heads), \
    (cg_bull, cg_bear, cg_info),  \
    (cd_bull, cd_bear, cd_heads), \
    (fg_bull, fg_bear, fg_info)   = await asyncio.gather(
        cp_task, cg_task, cd_task, fg_task
    )

    # Weighted scores
    # CryptoPanic 35%, CoinGecko 25%, CoinDesk 20%, Fear&Greed 20%
    weights = {"cp": 0.35, "cg": 0.25, "cd": 0.20, "fg": 0.20}

    total_bull = (
        cp_bull * weights["cp"] +
        cg_bull * weights["cg"] +
        cd_bull * weights["cd"] +
        fg_bull * weights["fg"]
    )
    total_bear = (
        cp_bear * weights["cp"] +
        cg_bear * weights["cg"] +
        cd_bear * weights["cd"] +
        fg_bear * weights["fg"]
    )

    net = total_bull - total_bear
    threshold = getattr(config, "NEWS_SENTIMENT_THRESHOLD", 3)

    if net > threshold:
        label = "BULLISH"
    elif net < -threshold:
        label = "BEARISH"
    else:
        label = "NEUTRAL"

    # সব headlines একসাথে
    all_heads = cp_heads + cd_heads
    all_heads.append(cg_info)
    all_heads.append(fg_info)

    return label, total_bull, total_bear, all_heads


# ── Main Filter Function ─────────────────────────────────────────────────────

async def check_news_sentiment(
    symbol: str,
    direction: str,
) -> Tuple[bool, str]:
    """
    Returns (passed, log_message).

    LONG  direction → blocked if strong BEARISH news
    SHORT direction → blocked if strong BULLISH news
    Neutral or fetch error → always passes
    """
    if not config.NEWS_SENTIMENT_ENABLED:
        return True, "NEWS: disabled — skipping ✅"

    coin      = _coin_symbol(symbol)
    cache_key = f"news_sentiment_v2:{coin}"

    cached = await cache.get(cache_key)
    if cached is not None:
        label, bull, bear, headlines = cached
    else:
        label, bull, bear, headlines = await _get_combined_sentiment(coin)
        await cache.set(
            cache_key,
            (label, bull, bear, headlines),
            ttl=getattr(config, "NEWS_CACHE_MINUTES", 15) * 60,
        )

    net          = bull - bear
    headline_str = " | ".join(headlines[:4]) if headlines else "no major news"

    # ── Block logic ──────────────────────────────────────────────────────────
    if label == "BULLISH" and direction == "SHORT":
        return False, (
            f"NEWS(4-source): BULLISH (net+{net:.1f}) — "
            f"SHORT blocked ❌ | {headline_str}"
        )

    if label == "BEARISH" and direction == "LONG":
        return False, (
            f"NEWS(4-source): BEARISH (net-{abs(net):.1f}) — "
            f"LONG blocked ❌ | {headline_str}"
        )

    if label == "BULLISH":
        return True, (
            f"NEWS(4-source): BULLISH (+{net:.1f}) — LONG aligns ✅ | {headline_str}"
        )

    if label == "BEARISH":
        return True, (
            f"NEWS(4-source): BEARISH (-{abs(net):.1f}) — SHORT aligns ✅ | {headline_str}"
        )

    return True, (
        f"NEWS(4-source): NEUTRAL (bull:{bull:.1f} bear:{bear:.1f}) — no block ✅ | {headline_str}"
    )
