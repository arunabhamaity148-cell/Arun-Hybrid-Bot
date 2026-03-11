"""
filters/sell_pressure.py — Filter 4E: Sell Pressure Check During Pullback

Problem this solves:
  Gainer/trending coins often do: pump → fake pullback → DUMP.
  Pullback hits 40% Fibonacci, all filters pass, you enter LONG.
  Then price dumps another 30%. Classic retail trap.

How to detect fake pullback vs healthy retracement:

  HEALTHY pullback (safe to buy):
    - Pullback candles have LOW volume (sellers are weak, no one selling hard)
    - Pullback candles have small bodies, lots of wicks (indecision, not conviction)
    - Pullback volume < pump volume (retracement is just profit taking, not distribution)

  DISTRIBUTION / fake pullback (avoid):
    - Pullback candles have HIGH volume (someone is dumping into the bounce)
    - Pullback candles have large red bodies (strong selling conviction)
    - Pullback volume >= pump volume (as much selling as buying = smart money exiting)

Two checks:
  Check 1 — Pullback Vol vs Pump Vol:
    Average volume of pullback candles / peak pump candle volume
    If ratio >= SELL_PRESSURE_VOL_RATIO_MAX → distribution, skip
    Default: 0.8 → pullback vol must be < 80% of pump vol

  Check 2 — Red Body Dominance:
    Count of large red body candles in pullback window
    If > SELL_PRESSURE_RED_BODY_MAX fraction → sellers controlling, skip
    Default: 0.6 → max 60% of pullback candles can have large red bodies

For SHORT direction: logic is inverted (checking buy pressure during bounce).
For core pairs: skipped (not pump-dump nature).
"""

import logging
import pandas as pd
import numpy as np
from typing import Tuple, Optional

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


def _find_pump_candle_volume(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 20,
) -> Optional[float]:
    """
    Find the volume of the strongest pump candle in recent lookback.
    LONG: biggest green candle (close > open) with highest volume
    SHORT: biggest red candle with highest volume
    Returns the volume of that candle.
    """
    recent = df.iloc[-lookback:]
    if len(recent) < 5:
        return None

    if direction == "LONG":
        green = recent[recent["close"] > recent["open"]]
        if green.empty:
            return None
        return float(green["volume"].max())
    else:
        red = recent[recent["close"] < recent["open"]]
        if red.empty:
            return None
        return float(red["volume"].max())


def _analyze_pullback_candles(
    df: pd.DataFrame,
    direction: str,
    pullback_candles: int = 5,
) -> Tuple[float, float]:
    """
    Analyze the most recent pullback_candles on the chart.

    Returns:
      avg_pullback_vol: average volume of pullback candles
      red_body_ratio: fraction of candles with large body in counter-direction

    For LONG pullback: counter-direction = red (bearish) candles
    For SHORT bounce: counter-direction = green (bullish) candles
    """
    # Last N closed candles (exclude current forming candle)
    window = df.iloc[-(pullback_candles + 1):-1]
    if len(window) < 3:
        return 0.0, 0.0

    avg_vol = float(window["volume"].mean())

    # Count candles with significant body in pullback direction
    body_sizes = (window["close"] - window["open"]).abs()
    candle_ranges = (window["high"] - window["low"])
    # Body must be > 40% of total range to count as "significant"
    significant_body = body_sizes > (candle_ranges * 0.4)

    if direction == "LONG":
        # Pullback = red candles (close < open)
        counter_candles = (window["close"] < window["open"]) & significant_body
    else:
        # Bounce = green candles (close > open)
        counter_candles = (window["close"] > window["open"]) & significant_body

    red_body_ratio = float(counter_candles.sum() / len(window))

    return avg_vol, red_body_ratio


async def check_sell_pressure(
    symbol: str,
    direction: str,
    is_core_pair: bool = False,
) -> Tuple[bool, str]:
    """
    Returns (passed, log_message).

    Passes if pullback shows weak selling (healthy retracement).
    Fails if pullback shows heavy selling (distribution / fake pullback).

    Skipped for core pairs.
    """
    # Core pairs skip — not pump-dump nature
    if is_core_pair and config.SELL_PRESSURE_SKIP_CORE_PAIRS:
        return True, "SELL_PRESSURE: Core pair — filter skipped ✅"

    try:
        df = await binance.get_klines(symbol, "15m", limit=35)
        if df.empty or len(df) < 15:
            return True, "SELL_PRESSURE: Insufficient data — allowing ✅"

        # ── Check 1: Pullback volume vs pump volume ───────────────────────────
        pump_vol = _find_pump_candle_volume(df, direction, lookback=20)
        avg_pullback_vol, red_body_ratio = _analyze_pullback_candles(
            df, direction, pullback_candles=config.SELL_PRESSURE_LOOKBACK_CANDLES
        )

        vol_ratio = None
        if pump_vol and pump_vol > 0:
            vol_ratio = avg_pullback_vol / pump_vol

        # ── Check 2: Red body dominance ───────────────────────────────────────
        max_vol_ratio = config.SELL_PRESSURE_VOL_RATIO_MAX
        max_red_ratio = config.SELL_PRESSURE_RED_BODY_MAX

        vol_ok = vol_ratio is None or vol_ratio < max_vol_ratio
        body_ok = red_body_ratio <= max_red_ratio

        vol_str = f"{vol_ratio:.2f}x pump vol" if vol_ratio is not None else "N/A"
        body_str = f"{red_body_ratio*100:.0f}% counter-body candles"

        if vol_ok and body_ok:
            # Healthy pullback
            pressure_level = "low" if (
                (vol_ratio is None or vol_ratio < 0.4) and red_body_ratio < 0.3
            ) else "moderate"
            msg = (
                f"SELL_PRESSURE: Healthy retracement — "
                f"vol: {vol_str} ✅ | body: {body_str} ✅ "
                f"[{pressure_level} pressure]"
            )
            return True, msg

        elif not vol_ok and not body_ok:
            # Both checks fail — strong distribution signal
            msg = (
                f"SELL_PRESSURE: ⚠️ Distribution detected — "
                f"vol: {vol_str} (max {max_vol_ratio}x) ❌ | "
                f"body: {body_str} (max {max_red_ratio*100:.0f}%) ❌ — skip"
            )
            return False, msg

        elif not vol_ok:
            # High volume pullback — sellers active
            msg = (
                f"SELL_PRESSURE: High pullback volume — "
                f"vol: {vol_str} (max {max_vol_ratio}x) ❌ | "
                f"body: {body_str} ✅ — skip"
            )
            return False, msg

        else:
            # Body ratio too high — strong candles against direction
            msg = (
                f"SELL_PRESSURE: Strong counter-candles — "
                f"vol: {vol_str} ✅ | "
                f"body: {body_str} (max {max_red_ratio*100:.0f}%) ❌ — skip"
            )
            return False, msg

    except Exception as exc:
        msg = f"SELL_PRESSURE: Error ({exc}) — allowing ✅"
        logger.warning(f"Sell pressure check failed for {symbol}: {exc}", exc_info=True)
        return True, msg
