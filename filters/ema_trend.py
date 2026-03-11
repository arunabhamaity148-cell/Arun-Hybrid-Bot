"""
filters/ema_trend.py — Filter 6: EMA Trend Confirmation (1h timeframe)
LONG only if price > EMA21 on 1h. SHORT only if price < EMA21 on 1h.
"""

import logging
import pandas as pd
from typing import Tuple, Optional

from data.binance_client import binance

logger = logging.getLogger(__name__)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


async def check_ema_trend(symbol: str, direction: str) -> Tuple[bool, str, Optional[float]]:
    try:
        df = await binance.get_klines(symbol, "1h", limit=50)
        if df.empty or len(df) < 22:
            return True, "EMA_TREND: Insufficient data — allowing ✅", None

        ema21 = _ema(df["close"], 21).iloc[-1]
        current_price = float(df["close"].iloc[-1])
        ema21_rounded = round(ema21, 8)

        if direction == "LONG":
            if current_price > ema21:
                msg = f"EMA_TREND: Price ({current_price:.8g}) above EMA21 ({ema21_rounded}) — LONG allowed ✅"
                return True, msg, ema21
            else:
                msg = f"EMA_TREND: Price ({current_price:.8g}) below EMA21 ({ema21_rounded}) — LONG blocked ❌"
                return False, msg, ema21
        else:
            if current_price < ema21:
                msg = f"EMA_TREND: Price ({current_price:.8g}) below EMA21 ({ema21_rounded}) — SHORT allowed ✅"
                return True, msg, ema21
            else:
                msg = f"EMA_TREND: Price ({current_price:.8g}) above EMA21 ({ema21_rounded}) — SHORT blocked ❌"
                return False, msg, ema21

    except Exception as exc:
        msg = f"EMA_TREND: Error ({exc}) — allowing ✅"
        logger.warning(f"EMA trend check failed for {symbol}: {exc}")
        return True, msg, None
