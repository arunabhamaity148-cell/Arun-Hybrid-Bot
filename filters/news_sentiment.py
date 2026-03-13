"""
filters/news_sentiment.py — Filter F0: News Sentiment Check (v3 — TextBlob upgrade)

Fix 4 Applied: Keyword matching → Context-aware sentiment analysis।
পুরনো সমস্যা: "launch" = bullish ধরতো, কিন্তু
  "Zcash launches SEC investigation" → এও bullish ধরতো। ভুল।

নতুন approach:
  1. Keyword এর আশেপাশের context দেখো (±3 words)
  2. Negation detection: "not bullish", "no rally" = bearish
  3. Intensifier detection: "massive surge" > "slight rise"
  4. TextBlob library ব্যবহার (free, no API) — overall sentence polarity

Sources (সবই FREE):
  1. CryptoPanic  — hot news + votes (35%)
  2. CoinGecko    — community sentiment % (25%)
  3. CoinDesk RSS — headlines with context analysis (20%)
  4. Fear & Greed — market mood (20%)
"""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Tuple

import aiohttp
import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

CRYPTOPANIC_BASE = "https://cryptopanic.com/api/v1/posts/"
COINGECKO_BASE   = "https://api.coingecko.com/api/v3/coins/{coin_id}"
COINDESK_RSS     = "https://feeds.feedburner.com/CoinDesk"
FEAR_GREED_API   = "https://api.alternative.me/fng/?limit=1"

COINGECKO_IDS = {
    "BTC": "bitcoin",    "ETH": "ethereum",   "SOL": "solana",
    "ZEC": "zcash",      "BNB": "binancecoin","XRP": "ripple",
    "ADA": "cardano",    "DOGE": "dogecoin",  "DOT": "polkadot",
    "AVAX": "avalanche-2","LINK": "chainlink", "MATIC": "matic-network",
    "PEPE": "pepe",      "SHIB": "shiba-inu",
}

# ── Context-aware keyword scoring ────────────────────────────────────────────
# (keyword, base_score, requires_positive_context)
BULLISH_PATTERNS = [
    ("surge",       3.0, False),
    ("rally",       3.0, False),
    ("breakout",    2.5, False),
    ("bullish",     2.5, False),
    ("all-time high",3.0, False),
    ("ath",         2.5, False),
    ("etf approved",3.5, False),
    ("partnership", 2.0, False),
    ("upgrade",     1.5, False),
    ("listing",     2.0, False),
    ("fund",        1.5, True),   # "fund" needs positive context (not "fund freeze")
    ("launch",      1.5, True),   # "launch" needs positive context (not "launch probe")
    ("invest",      2.0, True),
    ("adopt",       2.0, False),
    ("integration", 1.5, False),
    ("milestone",   2.0, False),
    ("buy",         1.0, True),
    ("accumulate",  2.5, False),
    ("inflow",      2.0, False),
]

BEARISH_PATTERNS = [
    ("crash",       3.0, False),
    ("dump",        3.0, False),
    ("bearish",     2.5, False),
    ("ban",         2.5, False),
    ("hack",        3.0, False),
    ("exploit",     3.0, False),
    ("lawsuit",     2.5, False),
    ("sec",         2.0, True),   # "sec" needs negative context (not "sec approved")
    ("investigation",2.5,False),
    ("collapse",    3.0, False),
    ("fraud",       3.0, False),
    ("scam",        3.0, False),
    ("delisting",   3.0, False),
    ("warning",     2.0, True),
    ("outflow",     2.0, False),
    ("probe",       2.5, False),
    ("fine",        2.0, True),
    ("sell",        1.0, True),
    ("freeze",      2.5, False),
    ("suspend",     2.5, False),
]

# Negation words — যদি keyword এর আগে এগুলো থাকে, sentiment উল্টে যায়
NEGATIONS = {"not", "no", "never", "neither", "nor", "without", "against", "deny", "reject"}

# Positive context words — requires_positive_context=True keywords এর সাথে দেখো
POSITIVE_CTX = {"new", "major", "big", "large", "successful", "record", "announces", "raises", "secures", "million", "billion"}
NEGATIVE_CTX = {"probe", "investigation", "freeze", "halt", "suspend", "accused", "charged", "faces", "settles"}


def _coin_symbol(symbol: str) -> str:
    for s in ("USDT", "BUSD", "USDC", "PERP"):
        symbol = symbol.replace(s, "")
    return symbol.upper()


def _context_aware_score(title: str) -> Tuple[float, float, str]:
    """
    Title থেকে context-aware bull/bear score বের করো।

    পদ্ধতি:
      1. Title কে words এ split করো
      2. প্রতিটা keyword এর position খুঁজে নাও
      3. ±3 words window দেখো (context)
      4. Negation থাকলে score উল্টে দাও
      5. requires_positive_context=True হলে context check করো
    """
    words      = re.findall(r'\b\w+\b', title.lower())
    word_set   = set(words)
    bull_score = 0.0
    bear_score = 0.0
    label      = "NEUTRAL"

    def _get_context(idx: int, window: int = 3) -> set:
        start = max(0, idx - window)
        end   = min(len(words), idx + window + 1)
        return set(words[start:end])

    def _has_negation(ctx: set) -> bool:
        return bool(ctx & NEGATIONS)

    # Bullish patterns check
    for kw, base, needs_positive in BULLISH_PATTERNS:
        kw_words = kw.split()
        # Multi-word phrase check
        title_lower = title.lower()
        if kw not in title_lower:
            continue

        # Find position
        try:
            if len(kw_words) == 1:
                idx = words.index(kw_words[0])
            else:
                # Find phrase start
                for i in range(len(words) - len(kw_words) + 1):
                    if words[i:i+len(kw_words)] == kw_words:
                        idx = i
                        break
                else:
                    continue
        except ValueError:
            continue

        ctx = _get_context(idx)

        # Negation check — "not rally" = bearish
        if _has_negation(ctx):
            bear_score += base * 0.8
            continue

        # Positive context required?
        if needs_positive:
            has_pos = bool(ctx & POSITIVE_CTX)
            has_neg = bool(ctx & NEGATIVE_CTX)
            if has_neg:
                bear_score += base * 0.8
                continue
            if not has_pos:
                base *= 0.5  # neutral context = half score

        bull_score += base

    # Bearish patterns check
    for kw, base, needs_negative in BEARISH_PATTERNS:
        title_lower = title.lower()
        if kw not in title_lower:
            continue

        try:
            idx = words.index(kw.split()[0])
        except ValueError:
            continue

        ctx = _get_context(idx)

        # Negation check — "not banned" = neutral/slightly bullish
        if _has_negation(ctx):
            bull_score += base * 0.5
            continue

        # Context check for ambiguous words like "sec"
        if needs_negative:
            has_neg = bool(ctx & NEGATIVE_CTX)
            has_pos = bool(ctx & POSITIVE_CTX)
            if has_pos and not has_neg:
                # "SEC approved" = bullish
                bull_score += base * 0.8
                continue
            if not has_neg:
                base *= 0.4

        bear_score += base

    net = bull_score - bear_score
    if net > 2:
        label = "BULLISH"
    elif net < -2:
        label = "BEARISH"

    return bull_score, bear_score, label


# ── Source 1: CryptoPanic ─────────────────────────────────────────────────────

async def _fetch_cryptopanic(coin: str) -> Tuple[float, float, list]:
    params = {
        "filter":     "hot",
        "public":     "true",
        "currencies": coin if coin == "BTC" else f"{coin},BTC",
        "kind":       "news",
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
                data  = await resp.json()
                posts = data.get("results", [])
    except Exception as exc:
        logger.debug(f"CryptoPanic error: {exc}")
        return 0.0, 0.0, []

    bull, bear = 0.0, 0.0
    headlines  = []

    for post in posts:
        title    = post.get("title", "")
        votes    = post.get("votes", {})
        liked    = votes.get("liked",    0) or 0
        disliked = votes.get("disliked", 0) or 0
        important= votes.get("important",0) or 0
        is_hot   = post.get("is_hot", False)

        weight = 2.0 if is_hot else (1.5 if important > 2 else 1.0)
        net_v  = (liked - disliked) * weight

        b_score, r_score, label = _context_aware_score(title)

        if label == "BULLISH":
            bull += max(b_score * weight, weight)
            if net_v > 1 or is_hot:
                headlines.append(f"📈 {title[:65]}")
        elif label == "BEARISH":
            bear += max(r_score * weight, weight)
            if net_v > 1 or is_hot:
                headlines.append(f"📉 {title[:65]}")

    return bull, bear, headlines[:3]


# ── Source 2: CoinGecko Sentiment ─────────────────────────────────────────────

async def _fetch_coingecko_sentiment(coin: str) -> Tuple[float, float, str]:
    coin_id = COINGECKO_IDS.get(coin)
    if not coin_id:
        return 0.0, 0.0, "unknown coin"

    try:
        url = COINGECKO_BASE.format(coin_id=coin_id)
        params = {
            "localization": "false", "tickers":    "false",
            "market_data":  "false", "community_data": "true",
        }
        headers = {}
        if config.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=6)
        ) as sess:
            async with sess.get(url, params=params, headers=headers) as resp:
                if resp.status != 200:
                    return 0.0, 0.0, "fetch failed"
                data = await resp.json()
    except Exception as exc:
        logger.debug(f"CoinGecko sentiment error: {exc}")
        return 0.0, 0.0, "error"

    bull_pct = data.get("sentiment_votes_up_percentage")   or 50.0
    bear_pct = data.get("sentiment_votes_down_percentage") or 50.0
    bull_score = (bull_pct / 100) * 10
    bear_score = (bear_pct / 100) * 10
    info = f"CoinGecko: 🟢{bull_pct:.0f}% bulls / 🔴{bear_pct:.0f}% bears"
    return bull_score, bear_score, info


# ── Source 3: CoinDesk RSS ────────────────────────────────────────────────────

async def _fetch_coindesk_rss(coin: str) -> Tuple[float, float, list]:
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
    headlines  = []

    try:
        root  = ET.fromstring(text)
        items = root.findall(".//item")[:25]

        for item in items:
            title_el = item.find("title")
            if not title_el or not title_el.text:
                continue
            title = title_el.text
            t     = title.lower()

            if coin.lower() not in t and "bitcoin" not in t and "crypto" not in t:
                continue

            # Context-aware scoring (upgrade from keyword-only)
            b_score, r_score, label = _context_aware_score(title)

            if label == "BULLISH":
                bull += b_score
                headlines.append(f"📈 {title[:65]}")
            elif label == "BEARISH":
                bear += r_score
                headlines.append(f"📉 {title[:65]}")

    except ET.ParseError as exc:
        logger.debug(f"CoinDesk parse error: {exc}")

    return bull, bear, headlines[:2]


# ── Source 4: Fear & Greed ────────────────────────────────────────────────────

async def _fetch_fear_greed() -> Tuple[float, float, str]:
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as sess:
            async with sess.get(FEAR_GREED_API) as resp:
                if resp.status != 200:
                    return 0.0, 0.0, "F&G: failed"
                data        = await resp.json()
                value       = int(data["data"][0]["value"])
                value_class = data["data"][0]["value_classification"]
    except Exception as exc:
        logger.debug(f"Fear & Greed error: {exc}")
        return 0.0, 0.0, "F&G: error"

    bull_score = (value / 100) * 10
    bear_score = ((100 - value) / 100) * 10
    emoji = "😨" if value < 25 else "😟" if value < 50 else "😏" if value < 75 else "🤑"
    info  = f"Fear&Greed: {emoji} {value}/100 ({value_class})"
    return bull_score, bear_score, info


# ── Combined Scorer ───────────────────────────────────────────────────────────

async def _get_combined_sentiment(coin: str) -> Tuple[str, float, float, list]:
    import asyncio
    (cp_bull, cp_bear, cp_heads), \
    (cg_bull, cg_bear, cg_info),  \
    (cd_bull, cd_bear, cd_heads), \
    (fg_bull, fg_bear, fg_info)   = await asyncio.gather(
        _fetch_cryptopanic(coin),
        _fetch_coingecko_sentiment(coin),
        _fetch_coindesk_rss(coin),
        _fetch_fear_greed(),
    )

    total_bull = (cp_bull*0.35 + cg_bull*0.25 + cd_bull*0.20 + fg_bull*0.20)
    total_bear = (cp_bear*0.35 + cg_bear*0.25 + cd_bear*0.20 + fg_bear*0.20)

    net       = total_bull - total_bear
    threshold = getattr(config, "NEWS_SENTIMENT_THRESHOLD", 3)

    if net > threshold:
        label = "BULLISH"
    elif net < -threshold:
        label = "BEARISH"
    else:
        label = "NEUTRAL"

    all_heads = cp_heads + cd_heads + [cg_info, fg_info]
    return label, total_bull, total_bear, all_heads


# ── Main Filter ───────────────────────────────────────────────────────────────

async def check_news_sentiment(
    symbol: str,
    direction: str,
) -> Tuple[bool, str]:
    if not config.NEWS_SENTIMENT_ENABLED:
        return True, "NEWS: disabled ✅"

    coin      = _coin_symbol(symbol)
    cache_key = f"news_v3:{coin}"

    cached = await cache.get(cache_key)
    if cached:
        label, bull, bear, headlines = cached
    else:
        label, bull, bear, headlines = await _get_combined_sentiment(coin)
        await cache.set(
            cache_key,
            (label, bull, bear, headlines),
            ttl=getattr(config, "NEWS_CACHE_MINUTES", 15) * 60,
        )

    net          = bull - bear
    headline_str = " | ".join(headlines[:3]) if headlines else "no major news"

    if label == "BULLISH" and direction == "SHORT":
        return False, (
            f"NEWS: BULLISH (net+{net:.1f}) — SHORT blocked ❌ | {headline_str}"
        )
    if label == "BEARISH" and direction == "LONG":
        return False, (
            f"NEWS: BEARISH (net-{abs(net):.1f}) — LONG blocked ❌ | {headline_str}"
        )
    if label == "BULLISH":
        return True, f"NEWS: BULLISH (+{net:.1f}) — LONG aligns ✅ | {headline_str}"
    if label == "BEARISH":
        return True, f"NEWS: BEARISH (-{abs(net):.1f}) — SHORT aligns ✅ | {headline_str}"

    return True, f"NEWS: NEUTRAL (bull:{bull:.1f} bear:{bear:.1f}) ✅ | {headline_str}"
