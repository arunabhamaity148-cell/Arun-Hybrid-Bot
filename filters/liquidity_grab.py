"""
filters/liquidity_grab.py — Filter 2: Liquidity Grab Detection
Detects wick-below-swing-low (LONG) or wick-above-swing-high (SHORT) patterns.
"""

import logging
import pandas as pd
import numpy as np
from typing import Tuple, Optional

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


def _find_swing_low(df: pd.DataFrame, lookback: int, left: int, right: int) -> Tuple[Optional[float], Optional[int]]:
    lows = df["low"].values
    n = len(lows)
    best_val = None
    best_idx = None
    for i in range(max(left, n - lookback), n - right):
        window_left = lows[i - left:i]
        window_right = lows[i + 1:i + right + 1]
        if len(window_left) < left or len(window_right) < right:
            continue
        if lows[i] <= min(window_left) and lows[i] <= min(window_right):
            best_val = lows[i]
            best_idx = i
    return best_val, best_idx


def _find_swing_high(df: pd.DataFrame, lookback: int, left: int, right: int) -> Tuple[Optional[float], Optional[int]]:
    highs = df["high"].values
    n = len(highs)
    best_val = None
    best_idx = None
    for i in range(max(left, n - lookback), n - right):
        window_left = highs[i - left:i]
        window_right = highs[i + 1:i + right + 1]
        if len(window_left) < left or len(window_right) < right:
            continue
        if highs[i] >= max(window_left) and highs[i] >= max(window_right):
            best_val = highs[i]
            best_idx = i
    return best_val, best_idx


def _detect_liq_grab_long(df: pd.DataFrame) -> Tuple[bool, Optional[float], Optional[int], Optional[int]]:
    swing_low, swing_idx = _find_swing_low(df, lookback=20, left=config.SWING_LEFT_BARS, right=config.SWING_RIGHT_BARS)
    if swing_low is None:
        return False, None, None, None

    recent = df.iloc[-config.LIQUIDITY_RECENT_CANDLES:]
    for i, (idx, row) in enumerate(recent.iterrows()):
        candles_ago = config.LIQUIDITY_RECENT_CANDLES - i
        if row["low"] < swing_low and row["close"] > swing_low:
            return True, swing_low, candles_ago, swing_idx
    return False, None, None, None


def _detect_liq_grab_short(df: pd.DataFrame) -> Tuple[bool, Optional[float], Optional[int], Optional[int]]:
    swing_high, swing_idx = _find_swing_high(df, lookback=20, left=config.SWING_LEFT_BARS, right=config.SWING_RIGHT_BARS)
    if swing_high is None:
        return False, None, None, None

    recent = df.iloc[-config.LIQUIDITY_RECENT_CANDLES:]
    for i, (idx, row) in enumerate(recent.iterrows()):
        candles_ago = config.LIQUIDITY_RECENT_CANDLES - i
        if row["high"] > swing_high and row["close"] < swing_high:
            return True, swing_high, candles_ago, swing_idx
    return False, None, None, None


async def check_liquidity_grab(symbol: str, direction: str) -> Tuple[bool, str, Optional[float], Optional[int]]:
    try:
        df = await binance.get_klines(symbol, "15m", limit=config.LIQUIDITY_LOOKBACK)
        if df.empty or len(df) < 25:
            return False, f"LIQ_GRAB: Insufficient data for {symbol} — skip ❌", None, None

        if direction == "LONG":
            detected, grab_level, candles_ago, _swing_idx = _detect_liq_grab_long(df)
        else:
            detected, grab_level, candles_ago, _swing_idx = _detect_liq_grab_short(df)

        if detected and grab_level is not None:
            msg = f"LIQ_GRAB: Detected at {grab_level:.8g} — {candles_ago} candle(s) ago ✅"
            return True, msg, grab_level, candles_ago
        else:
            msg = f"LIQ_GRAB: No grab in last {config.LIQUIDITY_RECENT_CANDLES} candles — skip ❌"
            return False, msg, None, None

    except Exception as exc:
        msg = f"LIQ_GRAB: Error ({exc}) — skip ❌"
        logger.warning(f"Liquidity grab check failed for {symbol}: {exc}", exc_info=True)
        return False, msg, None, None
