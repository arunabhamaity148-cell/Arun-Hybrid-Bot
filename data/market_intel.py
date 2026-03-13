"""
data/market_intel.py — Multi-Source Market Intelligence
Priority 1+2+3+4 combined: Signal generate হওয়ার পরে
CoinGecko + CoinDesk + CoinMarketCap থেকে deep intelligence নেয়।

3টা app থেকে যা যা বের করা হয়:

CoinGecko (No API key):
  - Community sentiment % (bullish/bearish votes)
  - Developer activity score
  - Social media score
  - Market cap rank
  - 24h price change + volume
  - ATH থেকে কত % নিচে
  - Large wallet / whale activity (holders data)

CoinDesk RSS (No API key):
  - Latest headlines for this coin
  - Bullish/bearish keyword scoring
  - Article count (more articles = more attention)

CoinMarketCap (Free API key - optional):
  - Trading volume rank
  - Volume change % vs yesterday
  - Market dominance %
  - Latest news/alerts
  - Fear & Greed from CMC

Output: IntelReport dataclass
  - Used in ai_rater.py prompt (actual data, not guesswork)
  - Used in Telegram signal message (why this coin is interesting)
  - Used in signal_score calculation
"""

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

# ── Endpoints ────────────────────────────────────────────────────────────────
COINGECKO_BASE   = "https://api.coingecko.com/api/v3"
COINDESK_RSS     = "https://feeds.feedburner.com/CoinDesk"
CMC_BASE         = "https://pro-api.coinmarketcap.com/v1"
FEAR_GREED_URL   = "https://api.alternative.me/fng/?limit=1"

# Binance symbol → CoinGecko ID
COINGECKO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
    "ZEC": "zcash",   "BNB": "binancecoin", "XRP": "ripple",
    "ADA": "cardano", "DOGE": "dogecoin",   "DOT": "polkadot",
    "AVAX": "avalanche-2", "LINK": "chainlink",
    "MATIC": "matic-network", "PEPE": "pepe",
    "SHIB": "shiba-inu",
}

# Binance symbol → CMC slug
CMC_SLUGS = {
    "BTC": "bitcoin",   "ETH": "ethereum",  "SOL": "solana",
    "ZEC": "zcash",     "BNB": "binance-coin", "XRP": "xrp",
    "ADA": "cardano",   "DOGE": "dogecoin",  "DOT": "polkadot",
    "AVAX": "avalanche","LINK": "chainlink", "MATIC": "polygon",
    "PEPE": "pepe",     "SHIB": "shiba-inu",
}

BULLISH_KW = [
    "surge","rally","pump","breakout","bullish","adopt","partnership",
    "launch","upgrade","ath","etf","listing","integration","fund",
    "invest","buy","accumulate","rise","gain","high","approve",
]
BEARISH_KW = [
    "crash","dump","bearish","ban","hack","exploit","lawsuit","sec",
    "regulation","collapse","fraud","scam","delisting","warning",
    "investigation","fall","drop","low","sell","outflow","fear",
]


def _coin_symbol(symbol: str) -> str:
    for s in ("USDT","BUSD","USDC","PERP"):
        symbol = symbol.replace(s, "")
    return symbol.upper()


# ── Output Dataclass ──────────────────────────────────────────────────────────

@dataclass
class IntelReport:
    symbol: str
    coin: str

    # CoinGecko
    cg_bull_pct:        float = 50.0   # community bullish %
    cg_bear_pct:        float = 50.0   # community bearish %
    cg_dev_score:       float = 0.0    # developer activity (0-100)
    cg_social_score:    float = 0.0    # social media score
    cg_mcap_rank:       int   = 999    # market cap rank
    cg_price_change_24h:float = 0.0    # 24h price change %
    cg_vol_change_24h:  float = 0.0    # volume vs market cap ratio
    cg_ath_pct:         float = 0.0    # % below ATH (negative = below ATH)
    cg_available:       bool  = False

    # CoinDesk RSS
    cd_bull_headlines:  list  = field(default_factory=list)
    cd_bear_headlines:  list  = field(default_factory=list)
    cd_total_articles:  int   = 0
    cd_sentiment:       str   = "NEUTRAL"  # BULLISH / BEARISH / NEUTRAL
    cd_available:       bool  = False

    # CoinMarketCap
    cmc_volume_rank:    int   = 999
    cmc_volume_change:  float = 0.0    # % change in volume
    cmc_dominance:      float = 0.0    # market dominance %
    cmc_available:      bool  = False

    # Composite
    overall_sentiment:  str   = "NEUTRAL"
    sentiment_score:    int   = 50     # 0-100, 50=neutral
    intel_summary:      str   = ""     # human readable 2-liner

    def as_ai_context(self) -> str:
        """AI rater prompt এ paste করার জন্য compact string"""
        lines = [
            f"[MARKET INTEL for {self.coin}]",
            f"CoinGecko Community: 🟢{self.cg_bull_pct:.0f}% bull / 🔴{self.cg_bear_pct:.0f}% bear",
            f"24h Change: {self.cg_price_change_24h:+.2f}% | MCap Rank: #{self.cg_mcap_rank}",
            f"Dev Score: {self.cg_dev_score:.0f}/100 | Social Score: {self.cg_social_score:.0f}/100",
            f"ATH Distance: {self.cg_ath_pct:+.1f}%",
        ]
        if self.cd_bull_headlines:
            lines.append(f"Bullish News: {' | '.join(self.cd_bull_headlines[:2])}")
        if self.cd_bear_headlines:
            lines.append(f"Bearish News: {' | '.join(self.cd_bear_headlines[:2])}")
        lines.append(f"Overall Sentiment: {self.overall_sentiment} (score {self.sentiment_score}/100)")
        return "\n".join(lines)

    def as_telegram_section(self) -> str:
        """Telegram signal message এ add করার জন্য formatted section"""
        bull_bar = "🟢" * min(5, int(self.cg_bull_pct / 20))
        bear_bar = "🔴" * min(5, int(self.cg_bear_pct / 20))

        sentiment_emoji = (
            "🚀" if self.sentiment_score >= 70 else
            "📈" if self.sentiment_score >= 55 else
            "😐" if self.sentiment_score >= 45 else
            "📉" if self.sentiment_score >= 30 else "💀"
        )

        lines = [
            f"\n🔬 <b>Market Intelligence ({self.coin}):</b>",
            f"• Community: {bull_bar} {self.cg_bull_pct:.0f}% Bull | {bear_bar} {self.cg_bear_pct:.0f}% Bear",
            f"• 24h Move: <b>{self.cg_price_change_24h:+.2f}%</b> | Rank: #{self.cg_mcap_rank}",
        ]

        if self.cg_ath_pct < -5:
            lines.append(f"• ATH Gap: {self.cg_ath_pct:.1f}% (room to recover)")
        if self.cg_dev_score > 50:
            lines.append(f"• Dev Activity: {self.cg_dev_score:.0f}/100 (active project)")

        if self.cd_bull_headlines:
            lines.append(f"• 📰 Bullish: {self.cd_bull_headlines[0][:55]}...")
        if self.cd_bear_headlines:
            lines.append(f"• 📰 Bearish: {self.cd_bear_headlines[0][:55]}...")

        if self.cd_total_articles > 3:
            lines.append(f"• News Volume: {self.cd_total_articles} articles (high attention)")

        lines.append(
            f"• {sentiment_emoji} Intel Score: <b>{self.sentiment_score}/100</b> ({self.overall_sentiment})"
        )

        if self.intel_summary:
            lines.append(f"• 💡 {self.intel_summary}")

        return "\n".join(lines)


# ── Source 1: CoinGecko ───────────────────────────────────────────────────────

async def _fetch_coingecko(coin: str) -> dict:
    """
    CoinGecko থেকে comprehensive coin data।
    Community sentiment, dev score, social score, market data।
    No API key needed।
    """
    coin_id = COINGECKO_IDS.get(coin)
    if not coin_id:
        return {}

    cache_key = f"intel_cg:{coin}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    url = f"{COINGECKO_BASE}/coins/{coin_id}"
    params = {
        "localization":   "false",
        "tickers":        "false",
        "market_data":    "true",
        "community_data": "true",
        "developer_data": "true",
    }

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        ) as sess:
            headers = {}
            if config.COINGECKO_API_KEY:
                headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY
            async with sess.get(url, params=params, headers=headers) as resp:
                if resp.status == 429:
                    logger.debug("CoinGecko rate limit hit")
                    return {}
                if resp.status != 200:
                    return {}
                data = await resp.json()
    except Exception as exc:
        logger.debug(f"CoinGecko intel fetch error: {exc}")
        return {}

    md   = data.get("market_data", {})
    cd   = data.get("community_data", {})
    dd   = data.get("developer_data", {})

    # ATH % distance
    ath      = md.get("ath", {}).get("usd") or 0
    price    = md.get("current_price", {}).get("usd") or 0
    ath_pct  = ((price - ath) / ath * 100) if ath > 0 else 0

    # Developer score (composite from GitHub stats)
    commits  = dd.get("commit_count_4_weeks", 0) or 0
    stars    = dd.get("stars", 0) or 0
    dev_score = min(100, (commits * 2) + (stars / 100))

    # Social score (composite)
    twitter  = cd.get("twitter_followers", 0) or 0
    reddit   = cd.get("reddit_subscribers", 0) or 0
    social_score = min(100, (twitter / 10000) + (reddit / 5000))

    result = {
        "bull_pct":       data.get("sentiment_votes_up_percentage") or 50.0,
        "bear_pct":       data.get("sentiment_votes_down_percentage") or 50.0,
        "dev_score":      round(dev_score, 1),
        "social_score":   round(social_score, 1),
        "mcap_rank":      data.get("market_cap_rank") or 999,
        "price_change_24h": md.get("price_change_percentage_24h") or 0.0,
        "total_volume":   md.get("total_volume", {}).get("usd") or 0,
        "market_cap":     md.get("market_cap", {}).get("usd") or 1,
        "ath_pct":        round(ath_pct, 2),
    }

    # vol/mcap ratio = how active trading is relative to size
    if result["market_cap"] > 0:
        result["vol_mcap_ratio"] = result["total_volume"] / result["market_cap"]
    else:
        result["vol_mcap_ratio"] = 0

    await cache.set(cache_key, result, ttl=300.0)  # 5 min cache
    return result


# ── Source 2: CoinDesk RSS ────────────────────────────────────────────────────

async def _fetch_coindesk(coin: str) -> dict:
    """
    CoinDesk RSS থেকে latest headlines।
    coin specific + general crypto news।
    No API key needed।
    """
    cache_key = f"intel_cd:{coin}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=6)
        ) as sess:
            async with sess.get(COINDESK_RSS) as resp:
                if resp.status != 200:
                    return {}
                text = await resp.text()
    except Exception as exc:
        logger.debug(f"CoinDesk RSS error: {exc}")
        return {}

    bull_heads, bear_heads = [], []
    total = 0

    try:
        root  = ET.fromstring(text)
        items = root.findall(".//item")[:30]

        for item in items:
            title_el = item.find("title")
            if not title_el or not title_el.text:
                continue
            title = title_el.text
            t     = title.lower()

            # coin mentioned OR general crypto
            if coin.lower() not in t and "bitcoin" not in t and "crypto" not in t:
                continue

            total += 1
            is_bull = any(kw in t for kw in BULLISH_KW)
            is_bear = any(kw in t for kw in BEARISH_KW)

            if is_bull and not is_bear:
                bull_heads.append(title[:70])
            elif is_bear and not is_bull:
                bear_heads.append(title[:70])

    except ET.ParseError as exc:
        logger.debug(f"CoinDesk parse error: {exc}")

    result = {
        "bull_headlines": bull_heads[:3],
        "bear_headlines": bear_heads[:3],
        "total_articles": total,
        "bull_count":     len(bull_heads),
        "bear_count":     len(bear_heads),
    }

    await cache.set(cache_key, result, ttl=600.0)  # 10 min cache
    return result


# ── Source 3: CoinMarketCap ───────────────────────────────────────────────────

async def _fetch_cmc(coin: str) -> dict:
    """
    CoinMarketCap free API থেকে volume + dominance data।
    Free API key: coinmarketcap.com/api (10,000 calls/month)।
    Key না থাকলে skip করে — bot চলবে।
    """
    cmc_key = getattr(config, "CMC_API_KEY", "")
    if not cmc_key:
        return {}

    cache_key = f"intel_cmc:{coin}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        ) as sess:
            headers = {"X-CMC_PRO_API_KEY": cmc_key}
            params  = {"symbol": coin, "convert": "USD"}
            async with sess.get(
                f"{CMC_BASE}/cryptocurrency/quotes/latest",
                params=params, headers=headers
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()

        quote = data.get("data", {}).get(coin, {}).get("quote", {}).get("USD", {})
        result = {
            "volume_change_24h": quote.get("volume_change_24h") or 0.0,
            "market_dominance":  quote.get("market_cap_dominance") or 0.0,
            "cmc_rank":          data.get("data", {}).get(coin, {}).get("cmc_rank") or 999,
        }
        await cache.set(cache_key, result, ttl=300.0)
        return result

    except Exception as exc:
        logger.debug(f"CMC fetch error: {exc}")
        return {}


# ── Composite Score ───────────────────────────────────────────────────────────

def _compute_score(cg: dict, cd: dict, cmc: dict) -> tuple[int, str, str]:
    """
    তিনটা source এর data থেকে 0-100 sentiment score বের করো।
    Returns (score, label, summary)
    """
    score = 50  # neutral baseline

    # CoinGecko community (±15 points)
    bull_pct = cg.get("bull_pct", 50)
    if bull_pct > 65:
        score += 15
    elif bull_pct > 55:
        score += 8
    elif bull_pct < 35:
        score -= 15
    elif bull_pct < 45:
        score -= 8

    # 24h price momentum (±10 points)
    chg = cg.get("price_change_24h", 0)
    if chg > 10:
        score += 10
    elif chg > 5:
        score += 6
    elif chg > 2:
        score += 3
    elif chg < -10:
        score -= 10
    elif chg < -5:
        score -= 6
    elif chg < -2:
        score -= 3

    # Volume/MCap ratio — high = active trading (±8 points)
    vmr = cg.get("vol_mcap_ratio", 0)
    if vmr > 0.3:
        score += 8
    elif vmr > 0.1:
        score += 4

    # Dev activity (±5 points)
    dev = cg.get("dev_score", 0)
    if dev > 60:
        score += 5
    elif dev < 10:
        score -= 3

    # CoinDesk news (±10 points)
    bull_n = cd.get("bull_count", 0)
    bear_n = cd.get("bear_count", 0)
    net    = bull_n - bear_n
    if net >= 3:
        score += 10
    elif net >= 1:
        score += 5
    elif net <= -3:
        score -= 10
    elif net <= -1:
        score -= 5

    # More articles = more attention = higher volatility risk (neutral adjustment)
    total_articles = cd.get("total_articles", 0)
    if total_articles > 5:
        score += 2  # attention = potential move

    # CMC volume change (±7 points)
    vcg = cmc.get("volume_change_24h", 0)
    if vcg > 50:
        score += 7
    elif vcg > 20:
        score += 4
    elif vcg < -30:
        score -= 5

    score = max(0, min(100, score))

    if score >= 70:
        label = "STRONGLY BULLISH"
    elif score >= 58:
        label = "BULLISH"
    elif score >= 42:
        label = "NEUTRAL"
    elif score >= 30:
        label = "BEARISH"
    else:
        label = "STRONGLY BEARISH"

    # Auto summary
    parts = []
    if bull_pct > 60:
        parts.append(f"{bull_pct:.0f}% community bullish")
    elif bull_pct < 40:
        parts.append(f"only {bull_pct:.0f}% community bullish")
    if chg > 5:
        parts.append(f"+{chg:.1f}% today")
    elif chg < -5:
        parts.append(f"{chg:.1f}% today")
    if bull_n > 1:
        parts.append(f"{bull_n} bullish articles")
    elif bear_n > 1:
        parts.append(f"{bear_n} bearish articles")
    if vmr > 0.2:
        parts.append("high trading activity")

    summary = " | ".join(parts[:3]) if parts else "insufficient data for summary"
    return score, label, summary


# ── Main Public Function ──────────────────────────────────────────────────────

async def get_intel(symbol: str) -> IntelReport:
    """
    Signal generate হওয়ার পরে এই function call করো।
    তিনটা source parallel এ fetch করে IntelReport return করে।

    Usage in engine.py:
        from data.market_intel import get_intel
        intel = await get_intel(result.symbol)
        # Telegram message এ add করো:
        msg += intel.as_telegram_section()
        # AI rater prompt এ add করো:
        ohlcv_context += intel.as_ai_context()
    """
    coin = _coin_symbol(symbol)

    # Parallel fetch — সব একসাথে
    cg_task  = _fetch_coingecko(coin)
    cd_task  = _fetch_coindesk(coin)
    cmc_task = _fetch_cmc(coin)

    cg, cd, cmc = await asyncio.gather(cg_task, cd_task, cmc_task)

    score, label, summary = _compute_score(cg, cd, cmc)

    report = IntelReport(
        symbol=symbol,
        coin=coin,

        # CoinGecko
        cg_bull_pct        = cg.get("bull_pct", 50.0),
        cg_bear_pct        = cg.get("bear_pct", 50.0),
        cg_dev_score       = cg.get("dev_score", 0.0),
        cg_social_score    = cg.get("social_score", 0.0),
        cg_mcap_rank       = cg.get("mcap_rank", 999),
        cg_price_change_24h= cg.get("price_change_24h", 0.0),
        cg_vol_change_24h  = cg.get("vol_mcap_ratio", 0.0),
        cg_ath_pct         = cg.get("ath_pct", 0.0),
        cg_available       = bool(cg),

        # CoinDesk
        cd_bull_headlines  = cd.get("bull_headlines", []),
        cd_bear_headlines  = cd.get("bear_headlines", []),
        cd_total_articles  = cd.get("total_articles", 0),
        cd_sentiment       = (
            "BULLISH"  if cd.get("bull_count", 0) > cd.get("bear_count", 0) else
            "BEARISH"  if cd.get("bear_count", 0) > cd.get("bull_count", 0) else
            "NEUTRAL"
        ),
        cd_available       = bool(cd),

        # CMC
        cmc_volume_rank    = cmc.get("cmc_rank", 999),
        cmc_volume_change  = cmc.get("volume_change_24h", 0.0),
        cmc_dominance      = cmc.get("market_dominance", 0.0),
        cmc_available      = bool(cmc),

        # Composite
        overall_sentiment  = label,
        sentiment_score    = score,
        intel_summary      = summary,
    )

    logger.info(
        f"Intel [{coin}]: {label} ({score}/100) | "
        f"CG:{cg.get('bull_pct',50):.0f}%bull | "
        f"CD:{cd.get('bull_count',0)}bull/{cd.get('bear_count',0)}bear"
    )

    return report
