"""
core/ai_rater.py — ChatGPT Signal Quality Rater (Priority 1 Update)

পুরনো সমস্যা:
  GPT কে শুধু text পাঠানো হতো (RR, regime, F&G)।
  GPT জানতো না price কোথায়, chart কেমন দেখাচ্ছে।
  Rating ছিল circular logic — bot এর filter result দেখে rate করা।

নতুন approach:
  1. Actual OHLCV data পাঠাও (last 15 candle)
  2. Key price levels পাঠাও (entry, SL, TP, grab, CHoCH)
  3. IntelReport থেকে CoinGecko + CoinDesk data পাঠাও
  4. Delta mark price vs Binance price পাঠাও (discrepancy check)
  এখন GPT সত্যিকার chart analysis করে rating দিতে পারবে।

Rating:
  A+ = Everything aligned, high conviction — full size নাও
  A  = Good setup, minor weakness — normal size
  B  = Marginal, কিছু weak — half size বা skip
  C  = Weak, multiple red flags — এড়িয়ে যাও
"""

import asyncio
import logging
from typing import Optional, TYPE_CHECKING

import aiohttp
import config

if TYPE_CHECKING:
    from data.market_intel import IntelReport

logger = logging.getLogger(__name__)


async def _get_ohlcv_summary(symbol: str) -> str:
    """
    Last 12 candle এর OHLCV data সংক্ষেপে।
    Delta data available হলে Delta থেকে, নইলে Binance থেকে।
    """
    try:
        # Priority: Delta → Binance fallback
        df = None

        if config.USE_DELTA_DATA:
            from data.delta_client import delta
            df = await delta.get_klines(symbol, "15m", limit=15)

        if df is None or df.empty:
            from data.binance_client import binance
            df = await binance.get_klines(symbol, "15m", limit=15)

        if df is None or df.empty:
            return "OHLCV: data unavailable"

        lines = []
        for _, row in df.tail(12).iterrows():
            direction = "🟢" if float(row["close"]) >= float(row["open"]) else "🔴"
            body_pct  = abs(float(row["close"]) - float(row["open"])) / float(row["open"]) * 100
            lines.append(
                f"{direction} O:{float(row['open']):.4g} H:{float(row['high']):.4g} "
                f"L:{float(row['low']):.4g} C:{float(row['close']):.4g} "
                f"Vol:{float(row['volume']):.0f} Body:{body_pct:.2f}%"
            )
        return "\n".join(lines)

    except Exception as exc:
        logger.debug(f"OHLCV summary error: {exc}")
        return "OHLCV: fetch failed"


async def _get_delta_price(symbol: str) -> Optional[float]:
    """Delta mark price — এটা actual trade price, Binance last price নয়।"""
    try:
        if not config.USE_DELTA_DATA:
            return None
        from data.delta_client import delta
        return await delta.get_mark_price(symbol)
    except Exception:
        return None


async def rate_signal(
    symbol:             str,
    direction:          str,
    rr:                 float,
    btc_regime:         str,
    fg_val:             int,
    fg_class:           str,
    session:            str,
    multitf_confluence: bool,
    pullback_pct:       Optional[float],
    pump_age_hr:        Optional[float],
    is_gainer:          bool,
    is_trending:        bool,
    sl_pct:             float,
    funding_rate_pct:   float = 0.0,
    funding_label:      str   = "N/A",
    entry:              Optional[float] = None,
    sl:                 Optional[float] = None,
    tp1:                Optional[float] = None,
    tp2:                Optional[float] = None,
    grab_level:         Optional[float] = None,
    choch_level:        Optional[float] = None,
    intel:              Optional["IntelReport"] = None,
) -> tuple[str, str]:
    """
    OpenAI API call করে signal rate করো।
    Returns (rating, reasoning) — e.g. ("A", "Strong CHoCH with volume...")

    On any failure returns ("N/A", "AI rating unavailable")
    """
    if not config.OPENAI_API_KEY or not config.SIGNAL_AI_RATING_ENABLED:
        return "N/A", "AI rating disabled"

    # Parallel fetch: OHLCV + Delta price
    ohlcv_task  = _get_ohlcv_summary(symbol)
    delta_task  = _get_delta_price(symbol)
    ohlcv_str, delta_price = await asyncio.gather(ohlcv_task, delta_task)

    # Price discrepancy check
    price_context = ""
    if delta_price and entry:
        diff_pct = abs(delta_price - entry) / entry * 100
        if diff_pct > 0.5:
            price_context = (
                f"\n⚠️ Price Discrepancy: "
                f"Entry based on Binance ({entry:.4g}) "
                f"but Delta mark price is {delta_price:.4g} "
                f"(diff {diff_pct:.2f}%) — entry may slip"
            )

    # Key levels string
    levels_str = "N/A"
    if entry and sl and tp1 and tp2:
        levels_str = (
            f"Entry: {entry:.6g} | SL: {sl:.6g} | "
            f"TP1: {tp1:.6g} | TP2: {tp2:.6g}"
        )
        if grab_level:
            levels_str += f" | Grab: {grab_level:.6g}"
        if choch_level:
            levels_str += f" | CHoCH: {choch_level:.6g}"

    # Intel context from CoinGecko + CoinDesk + CMC
    intel_str = intel.as_ai_context() if intel else "Market intel: unavailable"

    # Build context strings
    confluence_str = "YES — 15m+1h FVG aligned" if multitf_confluence else "NO — single TF only"
    pullback_str   = f"{pullback_pct:.1f}%" if pullback_pct else "N/A (core pair)"
    pump_str       = f"{pump_age_hr:.1f}hr ago" if pump_age_hr else "N/A (core pair)"
    pair_type      = "GAINER" if is_gainer else ("TRENDING" if is_trending else "CORE")

    if funding_rate_pct >= 0.10:
        funding_ctx = f"{funding_rate_pct:+.3f}% EXTREME LONG — dump risk"
    elif funding_rate_pct >= 0.04:
        funding_ctx = f"{funding_rate_pct:+.3f}% HIGH LONG — caution"
    elif funding_rate_pct <= -0.10:
        funding_ctx = f"{funding_rate_pct:+.3f}% EXTREME SHORT — pump risk"
    elif funding_rate_pct <= -0.04:
        funding_ctx = f"{funding_rate_pct:+.3f}% HIGH SHORT — caution"
    else:
        funding_ctx = f"{funding_rate_pct:+.3f}% NEUTRAL"

    prompt = f"""You are a strict crypto futures signal evaluator. Rate this signal A+/A/B/C.

=== SIGNAL DETAILS ===
Pair: {symbol} | Direction: {direction} | Type: {pair_type}
RR: {rr:.1f}:1 | SL Distance: {sl_pct:.1f}%
BTC Regime: {btc_regime} | Fear & Greed: {fg_val} ({fg_class})
Session: {session} | Multi-TF FVG: {confluence_str}
Funding Rate: {funding_ctx}
Pullback from pump: {pullback_str} | Pump age: {pump_str}
Key Levels: {levels_str}{price_context}

=== ACTUAL PRICE ACTION (15m, last 12 candles) ===
{ohlcv_str}

=== EXTERNAL MARKET INTEL ===
{intel_str}

=== RATING CRITERIA ===
A+ = RR≥3.0, Multi-TF confluence, London/NY session, BTC aligned,
     F&G normal (20-79), funding neutral/opposite, bullish intel,
     strong CHoCH candle visible in OHLCV
A  = RR≥2.5, most factors align, 1-2 minor weaknesses
B  = RR≥2.5 but weak session OR no confluence OR slightly crowded funding
     OR bearish news context OR pump old OR community mostly bearish
C  = Multiple red flags: pump old + no confluence + bad session +
     extreme F&G + extreme funding + bearish intel + price discrepancy

Analyze the actual candle data. Look for:
- Volume confirmation on CHoCH candle
- Clean structure or choppy/noisy price action
- Whether price is at a logical entry zone
- Community sentiment alignment with trade direction

Reply ONLY in this exact format (nothing else):
RATING: X
REASON: [max 18 words explaining the most important factor]"""

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        ) as session_http:
            async with session_http.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       config.OPENAI_MODEL,
                    "max_tokens":  80,
                    "temperature": 0.1,
                    "messages":    [{"role": "user", "content": prompt}],
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"OpenAI API returned {resp.status}")
                    return "N/A", "AI rating unavailable"

                data   = await resp.json()
                text   = data["choices"][0]["message"]["content"].strip()
                rating = "N/A"
                reason = "No reason provided"

                for line in text.split("\n"):
                    line = line.strip()
                    if line.startswith("RATING:"):
                        raw = line.replace("RATING:", "").strip().upper()
                        if raw in ("A+", "A", "B", "C"):
                            rating = raw
                    elif line.startswith("REASON:"):
                        reason = line.replace("REASON:", "").strip()

                logger.info(
                    f"AI Rating: {symbol} {direction} → {rating} | {reason}"
                )
                return rating, reason

    except asyncio.TimeoutError:
        logger.warning("OpenAI API timeout")
        return "N/A", "AI rating timeout"
    except Exception as exc:
        logger.warning(f"OpenAI API error: {exc}")
        return "N/A", "AI rating unavailable"


def rating_emoji(rating: str) -> str:
    return {
        "A+": "🌟", "A": "✅", "B": "⚠️", "C": "❌", "N/A": "➖",
    }.get(rating, "➖")


def should_suppress(rating: str) -> bool:
    if not config.SIGNAL_AI_SUPPRESS_LOW_RATING:
        return False
    return rating == "C"
