"""
filters/choch.py — Filter 3: Change of Character (CHoCH) Confirmation
After a liquidity grab, price must break opposite structure.
"""

import logging
import pandas as pd
from typing import Tuple, Optional

import config
from data.binance_client import binance
from filters.liquidity_grab import _find_swing_high, _find_swing_low

logger = logging.getLogger(__name__)


async def check_choch(symbol: str, direction: str, grab_candles_ago: Optional[int]) -> Tuple[bool, str, Optional[float]]:
    try:
        df = await binance.get_klines(symbol, "15m", limit=config.LIQUIDITY_LOOKBACK)
        if df.empty or len(df) < 25:
            return False, "CHOCH: Insufficient data — skip ❌", None

        if grab_candles_ago is None:
            return False, "CHOCH: No grab reference — skip ❌", None

        n = len(df)
        lookback_end = n - grab_candles_ago if grab_candles_ago < n else n
        pre_grab_df = df.iloc[:lookback_end]

        if len(pre_grab_df) < 10:
            return False, "CHOCH: Not enough pre-grab candles — skip ❌", None

        if direction == "LONG":
            break_level, _swing_idx = _find_swing_high(pre_grab_df, lookback=20, left=3, right=3)
            if break_level is None:
                return False, "CHOCH: No swing high found for CHoCH — skip ❌", None

            post_grab = df.iloc[-grab_candles_ago:] if grab_candles_ago < n else df.iloc[-5:]
            broke = post_grab[post_grab["close"] > break_level]
            if not broke.empty:
                return True, f"CHOCH: Confirmed — broke {break_level:.8g} ✅", break_level
            else:
                return False, f"CHOCH: Not confirmed — need close above {break_level:.8g} ❌", None

        else:  # SHORT
            break_level, _swing_idx = _find_swing_low(pre_grab_df, lookback=20, left=3, right=3)
            if break_level is None:
                return False, "CHOCH: No swing low found for CHoCH — skip ❌", None

            post_grab = df.iloc[-grab_candles_ago:] if grab_candles_ago < n else df.iloc[-5:]
            broke = post_grab[post_grab["close"] < break_level]
            if not broke.empty:
                return True, f"CHOCH: Confirmed — broke {break_level:.8g} ✅", break_level
            else:
                return False, f"CHOCH: Not confirmed — need close below {break_level:.8g} ❌", None

    except Exception as exc:
        msg = f"CHOCH: Error ({exc}) — skip ❌"
        logger.warning(f"CHoCH check failed for {symbol}: {exc}", exc_info=True)
        return False, msg, None
