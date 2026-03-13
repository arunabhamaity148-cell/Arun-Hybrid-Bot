"""
core/ai_rater.py — ChatGPT Signal Quality Rater

Signal generate হলে এই module OpenAI API কে call করে
একটা A+/A/B/C rating এবং ২ লাইনের reasoning পায়।

Rating মানে:
  A+ = সব কিছু align, high conviction — full size নাও
  A  = ভালো setup, minor weakness আছে — normal size
  B  = Marginal, কিছু একটা weak — half size বা skip
  C  = Weak setup, বেশিরভাগ সময় এড়িয়ে যাওয়া উচিত

SIGNAL_AI_SUPPRESS_LOW_RATING=True হলে C rating signal Telegram এ যাবে না।

API key না থাকলে বা call fail হলে rating "N/A" দিয়ে bot normally চলতে থাকে।
"""

import asyncio
import logging
import json
from typing import Optional

import aiohttp
import config

logger = logging.getLogger(__name__)


async def rate_signal(
    symbol: str,
    direction: str,
    rr: float,
    btc_regime: str,
    fg_val: int,
    fg_class: str,
    session: str,
    multitf_confluence: bool,
    pullback_pct: Optional[float],
    pump_age_hr: Optional[float],
    is_gainer: bool,
    is_trending: bool,
    sl_pct: float,
    funding_rate_pct: float = 0.0,
    funding_label: str = "N/A",
) -> tuple[str, str]:
    """
    Call OpenAI API to rate this signal.
    Returns (rating, reasoning) — e.g. ("A", "London open + Multi-TF confluence...")

    On any failure returns ("N/A", "AI rating unavailable")
    """
    if not config.OPENAI_API_KEY or not config.SIGNAL_AI_RATING_ENABLED:
        return "N/A", "AI rating disabled"

    # Build context string
    confluence_str = "YES — 15m+1h FVG aligned" if multitf_confluence else "NO — single TF only"
    pullback_str = f"{pullback_pct:.1f}%" if pullback_pct else "N/A (core pair)"
    pump_str = f"{pump_age_hr:.1f}hr ago" if pump_age_hr else "N/A (core pair)"
    pair_type = "GAINER" if is_gainer else ("TRENDING" if is_trending else "CORE")

    # Funding rate interpretation for prompt
    if funding_rate_pct >= 0.10:
        funding_context = f"{funding_rate_pct:+.3f}% EXTREME LONG — crowded, dump risk"
    elif funding_rate_pct >= 0.04:
        funding_context = f"{funding_rate_pct:+.3f}% HIGH LONG — caution"
    elif funding_rate_pct <= -0.10:
        funding_context = f"{funding_rate_pct:+.3f}% EXTREME SHORT — crowded, pump risk"
    elif funding_rate_pct <= -0.04:
        funding_context = f"{funding_rate_pct:+.3f}% HIGH SHORT — caution"
    else:
        funding_context = f"{funding_rate_pct:+.3f}% NEUTRAL — no crowd bias"

    prompt = f"""You are a strict crypto trading signal evaluator. Rate this signal A+/A/B/C.

Signal:
- Pair: {symbol} | Direction: {direction} | Pair type: {pair_type}
- RR: {rr:.1f}:1 | SL: {sl_pct:.1f}%
- BTC Regime: {btc_regime}
- Fear & Greed: {fg_val} ({fg_class})
- Session: {session}
- Multi-TF FVG Confluence: {confluence_str}
- Funding Rate: {funding_context}
- Pullback from pump: {pullback_str}
- Pump age: {pump_str}

Rating criteria:
A+ = RR>=3, confluence YES, London/NY session, BTC bull for LONG, F&G normal, funding neutral/opposite
A  = RR>=2.5, most things align, minor weakness
B  = RR>=2.5 but session weak, or no confluence, or funding slightly crowded
C  = Multiple weak factors — pump old, no confluence, bad session, extreme F&G, extreme funding

Reply in this exact format (nothing else):
RATING: X
REASON: [one sentence max 15 words explaining the rating]"""

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        ) as session_http:
            async with session_http.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.OPENAI_MODEL,
                    "max_tokens": 60,
                    "temperature": 0.1,
                    "messages": [{"role": "user", "content": prompt}],
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"OpenAI API returned {resp.status}")
                    return "N/A", "AI rating unavailable"

                data = await resp.json()
                text = data["choices"][0]["message"]["content"].strip()

                # Parse response
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

                logger.info(f"AI Rating: {symbol} {direction} → {rating} | {reason}")
                return rating, reason

    except asyncio.TimeoutError:
        logger.warning("OpenAI API timeout — skipping rating")
        return "N/A", "AI rating timeout"
    except Exception as exc:
        logger.warning(f"OpenAI API error: {exc}")
        return "N/A", "AI rating unavailable"


def rating_emoji(rating: str) -> str:
    """Return emoji for rating."""
    return {
        "A+": "🌟",
        "A":  "✅",
        "B":  "⚠️",
        "C":  "❌",
        "N/A": "➖",
    }.get(rating, "➖")


def should_suppress(rating: str) -> bool:
    """Return True if this signal should be suppressed based on rating."""
    if not config.SIGNAL_AI_SUPPRESS_LOW_RATING:
        return False
    return rating == "C"
