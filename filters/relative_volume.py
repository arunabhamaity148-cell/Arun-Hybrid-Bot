"""
filters/relative_volume.py — Filter 4D: Relative Volume Score (2-Layer Check)

Replaces the coarse "today's volume vs 20-day average" logic with smarter
intraday comparison.

Layer 1 — 1h Timeframe (Macro momentum):
  Compare last closed 1h candle volume vs same hour candle from yesterday.
  Rationale: Market has intraday patterns. 9AM always has higher volume than 3AM.
  Comparing to the same hour yesterday removes time-of-day bias.
  Threshold: RELVOL_1H_MIN_MULTIPLIER (default 1.5x, gainer pairs 2.0x)

Layer 2 — 15m Timeframe (Micro momentum):
  Compare last closed 15m candle vs average of previous 5 closed candles.
  Rationale: Catches real-time volume acceleration within the current move.
  Threshold: RELVOL_15M_MIN_MULTIPLIER (default 1.8x, gainer pairs 2.0x)

Scoring:
  Both layers pass  → STRONG volume confirmation ✅✅ (pass)
  Only 1h passes    → Macro strong, micro weak — marginal, pass with warning ⚠️
  Only 15m passes   → Micro spike only, could be noise — pass with warning ⚠️
  Both layers fail  → No real volume, skip ❌

For gainer/trending pairs: stricter thresholds applied automatically.
"""

import logging
import pandas as pd
from typing import Tuple, Optional

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


async def _get_1h_relative_volume(symbol: str, is_gainer: bool) -> Tuple[Optional[float], str]:
    """
    Compare last closed 1h candle volume vs same hour candle 24hr ago.
    Returns (ratio, description_str).
    """
    try:
        # Need 26+ candles to get current + 24hr-ago comparison
        df_1h = await binance.get_klines(symbol, "1h", limit=27)
        if df_1h.empty or len(df_1h) < 26:
            return None, "insufficient 1h data"

        # iloc[-2] = last fully closed 1h candle (iloc[-1] is still forming)
        current_vol = float(df_1h["volume"].iloc[-2])
        # Same hour yesterday = 24 candles back from the last closed
        same_hour_yesterday_vol = float(df_1h["volume"].iloc[-26])

        if same_hour_yesterday_vol == 0:
            return None, "zero yesterday volume"

        ratio = current_vol / same_hour_yesterday_vol
        threshold = config.RELVOL_GAINER_1H_MULTIPLIER if is_gainer else config.RELVOL_1H_MIN_MULTIPLIER

        return ratio, f"{ratio:.2f}x (threshold {threshold}x)"

    except Exception as exc:
        logger.debug(f"1h RelVol fetch failed for {symbol}: {exc}")
        return None, f"error: {exc}"


async def _get_15m_relative_volume(symbol: str, is_gainer: bool) -> Tuple[Optional[float], str]:
    """
    Compare last closed 15m candle vs average of previous 5 closed candles.
    Returns (ratio, description_str).
    """
    try:
        df_15m = await binance.get_klines(symbol, "15m", limit=10)
        if df_15m.empty or len(df_15m) < 7:
            return None, "insufficient 15m data"

        # iloc[-2] = last fully closed 15m candle
        current_vol = float(df_15m["volume"].iloc[-2])
        # Previous 5 closed candles avg: iloc[-7] to iloc[-2] exclusive
        prev_5_avg = df_15m["volume"].iloc[-7:-2].mean()

        if prev_5_avg == 0:
            return None, "zero 5-candle avg volume"

        ratio = current_vol / prev_5_avg
        threshold = config.RELVOL_GAINER_15M_MULTIPLIER if is_gainer else config.RELVOL_15M_MIN_MULTIPLIER

        return ratio, f"{ratio:.2f}x (threshold {threshold}x)"

    except Exception as exc:
        logger.debug(f"15m RelVol fetch failed for {symbol}: {exc}")
        return None, f"error: {exc}"


async def check_relative_volume(
    symbol: str,
    direction: str,
    is_gainer: bool = False,
) -> Tuple[bool, str]:
    """
    Returns (passed, log_message).

    Both layers fail = hard skip.
    One or both pass = continue (with appropriate warning/confirmation tag).
    """
    try:
        # Determine thresholds based on pair type
        thresh_1h = config.RELVOL_GAINER_1H_MULTIPLIER if is_gainer else config.RELVOL_1H_MIN_MULTIPLIER
        thresh_15m = config.RELVOL_GAINER_15M_MULTIPLIER if is_gainer else config.RELVOL_15M_MIN_MULTIPLIER
        pair_label = "gainer" if is_gainer else "standard"

        # Fetch both layers concurrently
        ratio_1h, desc_1h = await _get_1h_relative_volume(symbol, is_gainer)
        ratio_15m, desc_15m = await _get_15m_relative_volume(symbol, is_gainer)

        # Evaluate each layer
        layer1_pass = ratio_1h is not None and ratio_1h >= thresh_1h
        layer2_pass = ratio_15m is not None and ratio_15m >= thresh_15m

        # ── Decision ─────────────────────────────────────────────────────────

        if layer1_pass and layer2_pass:
            msg = (
                f"RELVOL: ✅✅ Both layers strong [{pair_label}] — "
                f"1h: {desc_1h} | 15m: {desc_15m}"
            )
            return True, msg

        elif layer1_pass and not layer2_pass:
            msg = (
                f"RELVOL: Macro strong, micro weak [{pair_label}] — "
                f"1h: {desc_1h} ✅ | 15m: {desc_15m} ⚠️ — passing"
            )
            return True, msg

        elif not layer1_pass and layer2_pass:
            msg = (
                f"RELVOL: Micro spike only [{pair_label}] — "
                f"1h: {desc_1h} ⚠️ | 15m: {desc_15m} ✅ — passing cautiously"
            )
            return True, msg

        else:
            # Both fail
            r1_str = f"{ratio_1h:.2f}x" if ratio_1h is not None else "N/A"
            r2_str = f"{ratio_15m:.2f}x" if ratio_15m is not None else "N/A"
            msg = (
                f"RELVOL: Both layers weak [{pair_label}] — "
                f"1h: {r1_str} (need {thresh_1h}x) | "
                f"15m: {r2_str} (need {thresh_15m}x) ❌"
            )
            return False, msg

    except Exception as exc:
        msg = f"RELVOL: Error ({exc}) — allowing ✅"
        logger.warning(f"Relative volume check failed for {symbol}: {exc}", exc_info=True)
        return True, msg
