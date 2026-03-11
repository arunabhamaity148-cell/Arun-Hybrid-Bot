"""
filters/fvg.py — Filter 4: Fair Value Gap (FVG) Detection
3-candle pattern: gap between candle[i-2] high and candle[i] low (bullish FVG).
"""

import logging
import pandas as pd
from typing import Tuple, Optional

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


def _find_fvg(df: pd.DataFrame, direction: str) -> Optional[Tuple[float, float]]:
    n = len(df)
    lookback = min(config.FVG_LOOKBACK, n - 2)

    for i in range(n - 1, n - lookback - 1, -1):
        if i < 2:
            break
        c1 = df.iloc[i - 2]
        c3 = df.iloc[i]

        if direction == "LONG":
            fvg_low = c1["high"]
            fvg_high = c3["low"]
            if fvg_high > fvg_low:
                return (fvg_low, fvg_high)
        else:
            fvg_high = c1["low"]
            fvg_low = c3["high"]
            if fvg_high > fvg_low:
                return (fvg_low, fvg_high)

    return None


async def check_fvg(symbol: str, direction: str, current_price: Optional[float] = None) -> Tuple[bool, str, Optional[float], Optional[float]]:
    try:
        df = await binance.get_klines(symbol, "15m", limit=50)
        if df.empty or len(df) < 5:
            return False, "FVG: Insufficient data — skip ❌", None, None

        if current_price is None:
            current_price = float(df["close"].iloc[-1])

        fvg = _find_fvg(df, direction)
        if fvg is None:
            return False, "FVG: No fair value gap found in last 10 candles ❌", None, None

        fvg_low, fvg_high = fvg
        mid = (fvg_low + fvg_high) / 2
        tolerance = mid * config.FVG_ENTRY_TOLERANCE_PCT

        in_zone = (fvg_low - tolerance) <= current_price <= (fvg_high + tolerance)

        if in_zone:
            msg = f"FVG: Found {fvg_low:.8g}–{fvg_high:.8g}, price entering ({current_price:.8g}) ✅"
            return True, msg, fvg_low, fvg_high
        else:
            msg = f"FVG: Price not in FVG zone (need {fvg_low:.8g}–{fvg_high:.8g}, current {current_price:.8g}) ❌"
            return False, msg, None, None

    except Exception as exc:
        msg = f"FVG: Error ({exc}) — skip ❌"
        logger.warning(f"FVG check failed for {symbol}: {exc}")
        return False, msg, None, None
