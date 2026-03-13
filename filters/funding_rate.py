"""
filters/funding_rate.py — Filter 4F: Funding Rate Check

Funding rate কী:
  Binance Futures এ প্রতি ৮ ঘন্টায় long/short holders এর মধ্যে payment হয়।
  Positive rate = long holders pay short holders (বাজারে বেশি LONG)
  Negative rate = short holders pay long holders (বাজারে বেশি SHORT)

কীভাবে filter কাজ করে:

  LONG signal এ:
    rate > +0.10% (EXTREME_LONG) → Skip — সবাই already long, dump risk high
    rate +0.04% to +0.10% (HIGH_LONG) → Warn, allow with caution
    rate -0.04% to +0.04% (NEUTRAL) → Normal, allow ✅
    rate < -0.04% (HIGH_SHORT / EXTREME_SHORT) → Strong LONG, short squeeze likely ✅✅

  SHORT signal এ:
    rate < -0.10% (EXTREME_SHORT) → Skip — সবাই already short, pump risk high
    rate -0.10% to -0.04% (HIGH_SHORT) → Warn, allow with caution
    rate -0.04% to +0.04% (NEUTRAL) → Normal, allow ✅
    rate > +0.04% (HIGH_LONG / EXTREME_LONG) → Strong SHORT, long squeeze likely ✅✅

Real example:
  SOLUSDT funding = +0.15%, bot gives LONG signal
  → Everyone already long → when price dips, mass exit → SL hit
  → Skip this signal

  SOLUSDT funding = -0.08%, bot gives LONG signal
  → Many shorts are trapped → small pump → short squeeze → TP2 easily hit
  → Take this signal with confidence
"""

import logging
from typing import Tuple

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


async def check_funding_rate(
    symbol: str,
    direction: str,
) -> Tuple[bool, str, float]:
    """
    Returns (passed, log_message, rate_pct).

    rate_pct is passed back so engine can include it in Telegram message
    and AI rater prompt.
    """
    try:
        fr = await binance.get_funding_rate(symbol)
        rate_pct = fr["rate_pct"]
        label = fr["label"]
        bias = fr["bias"]

        extreme_threshold = config.FUNDING_EXTREME_THRESHOLD   # 0.10%
        high_threshold = config.FUNDING_HIGH_THRESHOLD         # 0.04%

        if direction == "LONG":
            if rate_pct >= extreme_threshold:
                # Crowded long — high squeeze/dump risk
                msg = (
                    f"FUNDING: {rate_pct:+.3f}% [{label}] — "
                    f"crowded LONG, dump risk high ❌"
                )
                return False, msg, rate_pct

            elif rate_pct >= high_threshold:
                # Many longs — warn but allow
                msg = (
                    f"FUNDING: {rate_pct:+.3f}% [{label}] — "
                    f"many longs, proceed with caution ⚠️ (allowed)"
                )
                return True, msg, rate_pct

            elif rate_pct <= -high_threshold:
                # Crowded short — LONG squeeze likely = strong setup
                msg = (
                    f"FUNDING: {rate_pct:+.3f}% [{label}] — "
                    f"shorts crowded, squeeze likely ✅✅ HIGH CONVICTION"
                )
                return True, msg, rate_pct

            else:
                # Neutral
                msg = (
                    f"FUNDING: {rate_pct:+.3f}% [NEUTRAL] — "
                    f"no crowd bias ✅"
                )
                return True, msg, rate_pct

        else:  # SHORT
            if rate_pct <= -extreme_threshold:
                # Crowded short — high squeeze/pump risk
                msg = (
                    f"FUNDING: {rate_pct:+.3f}% [{label}] — "
                    f"crowded SHORT, pump risk high ❌"
                )
                return False, msg, rate_pct

            elif rate_pct <= -high_threshold:
                # Many shorts — warn but allow
                msg = (
                    f"FUNDING: {rate_pct:+.3f}% [{label}] — "
                    f"many shorts, proceed with caution ⚠️ (allowed)"
                )
                return True, msg, rate_pct

            elif rate_pct >= high_threshold:
                # Crowded long — SHORT squeeze likely = strong setup
                msg = (
                    f"FUNDING: {rate_pct:+.3f}% [{label}] — "
                    f"longs crowded, squeeze likely ✅✅ HIGH CONVICTION"
                )
                return True, msg, rate_pct

            else:
                # Neutral
                msg = (
                    f"FUNDING: {rate_pct:+.3f}% [NEUTRAL] — "
                    f"no crowd bias ✅"
                )
                return True, msg, rate_pct

    except Exception as exc:
        msg = f"FUNDING: Error ({exc}) — allowing ✅"
        logger.warning(f"Funding rate check failed for {symbol}: {exc}")
        return True, msg, 0.0
