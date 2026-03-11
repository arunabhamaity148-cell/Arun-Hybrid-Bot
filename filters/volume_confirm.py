"""
filters/volume_confirm.py — Filter 5: Volume Confirmation
CHoCH candle must have volume > 2x 20-period average.
News-flagged coins use relaxed 1.5x threshold.
"""

import logging
import pandas as pd
from typing import Tuple, Optional

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


async def check_volume_confirm(
    symbol: str,
    direction: str,
    news_mode: bool = False,
    grab_candles_ago: Optional[int] = None,
) -> Tuple[bool, str]:
    try:
        df = await binance.get_klines(symbol, "15m", limit=30)
        if df.empty or len(df) < 22:
            return False, "VOLUME: Insufficient data — skip ❌"

        avg_vol = df["volume"].iloc[-21:-1].mean()

        if avg_vol == 0:
            return False, "VOLUME: Zero average volume — skip ❌"

        if grab_candles_ago is not None and grab_candles_ago >= 2:
            post_grab_end = len(df) - 1
            post_grab_start = max(0, len(df) - grab_candles_ago)
            choch_vol_series = df["volume"].iloc[post_grab_start:post_grab_end]
            if choch_vol_series.empty:
                choch_vol = df["volume"].iloc[-4:-1].max()
                vol_source = "last 3 candles (fallback)"
            else:
                choch_vol = choch_vol_series.max()
                vol_source = f"post-grab window ({len(choch_vol_series)} candles)"
        else:
            choch_vol = df["volume"].iloc[-4:-1].max()
            vol_source = "last 3 closed candles"

        multiplier = choch_vol / avg_vol
        threshold = 1.5 if news_mode else config.CHOCH_VOLUME_MULTIPLIER
        rounded = round(multiplier, 2)
        news_label = " (news relaxed 1.5x)" if news_mode else ""

        if multiplier >= threshold:
            msg = f"VOLUME: CHoCH candle {rounded}x avg [{vol_source}]{news_label} — confirmed ✅"
            return True, msg
        else:
            msg = f"VOLUME: Only {rounded}x avg (need {threshold}x) [{vol_source}] — weak, skip ❌"
            return False, msg

    except Exception as exc:
        msg = f"VOLUME: Error ({exc}) — skip ❌"
        logger.warning(f"Volume confirm check failed for {symbol}: {exc}")
        return False, msg
