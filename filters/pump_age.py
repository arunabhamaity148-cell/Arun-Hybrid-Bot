"""
filters/pump_age.py — Filter 4C: Pump Age Detection

Logic:
  Scan last PUMP_AGE_MAX_CANDLES (default: 8 × 15m = 2 hours) on 15m chart.
  Find the candle where the big pump/dump STARTED — identified by:
    - Volume spike >= PUMP_IDENTIFY_VOL_MULTIPLIER × 20-candle avg
    - AND significant price move in the direction

  If the pump start candle is within PUMP_AGE_MAX_CANDLES → fresh, trade it.
  If pump start is older than PUMP_AGE_MAX_CANDLES → stale, skip.

Why this matters for gainer/trending pairs:
  Gainer list updates every 5min but the actual pump may have happened hours ago.
  Example: PEPE pumped 18% at 6AM IST. It's now 11AM IST.
  The scanner picks it up as a "top gainer" but the move is 5 hours old.
  Entering now = buying near the top after retail already bought.

  Fresh pump (< 2hr) = smart money still active, continuation possible
  Old pump (> 2hr) = retail holding bags, distribution phase

This filter is SKIPPED for core pairs (BTC/ETH etc) — they don't have
single explosive pump candles; they trend gradually.
"""

import logging
import pandas as pd
import numpy as np
from typing import Tuple, Optional

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


def _find_pump_start_candle(
    df: pd.DataFrame,
    direction: str,
    vol_multiplier: float,
) -> Optional[int]:
    """
    Find the most recent candle that started the pump/dump.

    Criteria for a pump start candle:
    1. Volume >= vol_multiplier × 20-candle rolling avg
    2. Price move >= 1.5% in the direction (body, not wick)
    3. Candle closed in the direction (green for LONG, red for SHORT)

    Returns: candles_ago (int) from current bar, or None if not found.
    The lower the number, the fresher the pump.
    """
    if len(df) < 25:
        return None

    # 20-candle rolling avg volume (exclude last 1 candle = current forming)
    vol_avg = df["volume"].iloc[-21:-1].mean()
    if vol_avg == 0:
        return None

    # Search in last 30 candles (covers max 7.5 hrs on 15m)
    search_window = df.iloc[-30:]
    n = len(search_window)

    for i in range(n - 1, -1, -1):  # newest first
        row = search_window.iloc[i]
        candles_ago = n - 1 - i  # 0 = most recent closed candle

        vol_ratio = row["volume"] / vol_avg
        if vol_ratio < vol_multiplier:
            continue

        # Price body move
        body_move_pct = (row["close"] - row["open"]) / row["open"] * 100

        if direction == "LONG":
            # Green candle with >= 1.5% body
            if body_move_pct >= 1.5:
                return candles_ago
        else:
            # Red candle with <= -1.5% body
            if body_move_pct <= -1.5:
                return candles_ago

    return None


async def check_pump_age(
    symbol: str,
    direction: str,
    is_core_pair: bool = False,
) -> Tuple[bool, str]:
    """
    Returns (passed, log_message).

    Passes if the initiating pump candle is within PUMP_AGE_MAX_CANDLES.
    Skips for core pairs.
    """
    # Core pairs skip
    if is_core_pair and config.PUMP_AGE_SKIP_CORE_PAIRS:
        return True, "PUMP_AGE: Core pair — filter skipped ✅"

    try:
        df = await binance.get_klines(symbol, "15m", limit=60)
        if df.empty or len(df) < 25:
            return True, "PUMP_AGE: Insufficient data — allowing ✅"

        pump_candles_ago = _find_pump_start_candle(
            df,
            direction,
            config.PUMP_IDENTIFY_VOL_MULTIPLIER,
        )

        max_age = config.PUMP_AGE_MAX_CANDLES
        max_age_hours = max_age * 15 / 60  # convert 15m candles to hours

        if pump_candles_ago is None:
            # No clear pump candle found — could mean gradual move (acceptable)
            # or no pump at all (also acceptable for core pairs logic)
            return True, "PUMP_AGE: No single pump candle found — gradual move, allowing ✅"

        age_hours = round(pump_candles_ago * 15 / 60, 1)

        if pump_candles_ago <= max_age:
            msg = (
                f"PUMP_AGE: Pump started {pump_candles_ago} candles ago "
                f"({age_hours}hr) — fresh momentum ✅"
            )
            return True, msg
        else:
            msg = (
                f"PUMP_AGE: Pump started {pump_candles_ago} candles ago "
                f"({age_hours}hr) — too old (max {max_age_hours}hr), "
                f"late entry risk ❌"
            )
            return False, msg

    except Exception as exc:
        msg = f"PUMP_AGE: Error ({exc}) — allowing ✅"
        logger.warning(f"Pump age check failed for {symbol}: {exc}", exc_info=True)
        return True, msg
