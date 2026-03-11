"""
filters/pullback_quality.py — Filter 4B: Pullback Quality Check (Fibonacci Retracement)

Logic:
  1. Find the pump peak in last PULLBACK_LOOKBACK_CANDLES (default: last 24hr on 15m)
  2. Find the base (start of pump) — lowest point before the peak
  3. Calculate how much price has retraced from peak to current
  4. Accept only 30%–62% retracement (Fibonacci golden zone)

Why Fibonacci golden zone (30–62%):
  < 30% = price barely pulled back, pump still live, you're chasing
           Smart money hasn't finished distributing yet
  30–62% = healthy pullback, FVG/OB zone, institutional re-accumulation
           This is where smart money buys back — best R:R
  62–78% = deep retracement, pump structure weakening, risky
  > 78%  = pump structure likely broken, next move could be further down

This filter is SKIPPED for core pairs (BTC/ETH/SOL/BNB/DOGE) because
they trend steadily — they don't have single pump-and-retrace patterns.
"""

import logging
import pandas as pd
import numpy as np
from typing import Tuple, Optional

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


def _find_pump_peak_and_base(
    df: pd.DataFrame,
    direction: str,
    lookback: int,
) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    """
    Find pump peak and base in the lookback window.

    For LONG (bullish pump):
      - Peak = highest high in lookback window
      - Base = lowest low BEFORE the peak candle
      Returns (peak_price, base_price, peak_index)

    For SHORT (bearish dump):
      - Peak = lowest low in lookback window (the dump bottom)
      - Base = highest high BEFORE the peak candle
      Returns (peak_price, base_price, peak_index)
    """
    recent = df.iloc[-lookback:]
    if len(recent) < 10:
        return None, None, None

    if direction == "LONG":
        peak_idx_local = recent["high"].idxmax()
        peak_price = float(recent["high"].max())

        # Base = lowest low in candles BEFORE the peak
        peak_pos = recent.index.get_loc(peak_idx_local)
        if peak_pos < 3:
            return None, None, None
        before_peak = recent.iloc[:peak_pos]
        base_price = float(before_peak["low"].min())
        pump_size = peak_price - base_price

    else:  # SHORT — dump
        peak_idx_local = recent["low"].idxmin()
        peak_price = float(recent["low"].min())

        peak_pos = recent.index.get_loc(peak_idx_local)
        if peak_pos < 3:
            return None, None, None
        before_peak = recent.iloc[:peak_pos]
        base_price = float(before_peak["high"].max())
        pump_size = base_price - peak_price

    if pump_size <= 0:
        return None, None, None

    return peak_price, base_price, peak_pos


def _calculate_retracement_pct(
    peak: float,
    base: float,
    current: float,
    direction: str,
) -> Optional[float]:
    """
    Calculate how much % price has retraced from peak back toward base.

    LONG: pump went base→peak. Retracement = (peak - current) / (peak - base) * 100
    SHORT: dump went base→peak (low). Retracement = (current - peak) / (base - peak) * 100
    """
    if direction == "LONG":
        pump_size = peak - base
        if pump_size <= 0:
            return None
        retrace = (peak - current) / pump_size * 100
    else:
        pump_size = base - peak  # base is the high, peak is the low
        if pump_size <= 0:
            return None
        retrace = (current - peak) / pump_size * 100

    return round(retrace, 1)


async def check_pullback_quality(
    symbol: str,
    direction: str,
    current_price: Optional[float] = None,
    is_core_pair: bool = False,
) -> Tuple[bool, str]:
    """
    Returns (passed, log_message).

    Skips for core pairs if PULLBACK_SKIP_CORE_PAIRS=True.
    Passes if retracement is between PULLBACK_MIN_PCT and PULLBACK_MAX_PCT.
    """
    # Skip for core pairs — they don't follow single-pump retracement logic
    if is_core_pair and config.PULLBACK_SKIP_CORE_PAIRS:
        return True, "PULLBACK: Core pair — filter skipped ✅"

    try:
        df = await binance.get_klines(symbol, "15m", limit=config.PULLBACK_LOOKBACK_CANDLES + 10)
        if df.empty or len(df) < 20:
            return True, "PULLBACK: Insufficient data — allowing ✅"

        if current_price is None:
            current_price = float(df["close"].iloc[-1])

        peak, base, peak_pos = _find_pump_peak_and_base(
            df, direction, config.PULLBACK_LOOKBACK_CANDLES
        )

        if peak is None or base is None:
            return True, "PULLBACK: No clear pump structure found — allowing ✅"

        # Minimum pump size check: must be at least 3% to matter
        if direction == "LONG":
            pump_pct = (peak - base) / base * 100
        else:
            pump_pct = (base - peak) / base * 100

        if pump_pct < 3.0:
            return True, f"PULLBACK: Pump too small ({pump_pct:.1f}%) to measure retracement — allowing ✅"

        retrace_pct = _calculate_retracement_pct(peak, base, current_price, direction)

        if retrace_pct is None:
            return True, "PULLBACK: Retracement calc error — allowing ✅"

        min_r = config.PULLBACK_MIN_PCT
        max_r = config.PULLBACK_MAX_PCT

        # ── Decision ─────────────────────────────────────────────────────────

        if retrace_pct < min_r:
            msg = (
                f"PULLBACK: Only {retrace_pct:.1f}% retrace from {pump_pct:.1f}% pump "
                f"(need {min_r}%–{max_r}%) — too shallow, still pumping ❌"
            )
            return False, msg

        elif retrace_pct > 78.0:
            msg = (
                f"PULLBACK: {retrace_pct:.1f}% retrace — structure likely broken "
                f"(>{78}% = invalidated) ❌"
            )
            return False, msg

        elif retrace_pct > max_r:
            # Between 62–78%: deep but not broken — warn but allow
            msg = (
                f"PULLBACK: {retrace_pct:.1f}% retrace — deeper than golden zone "
                f"({max_r}%) but structure intact ⚠️ — allowing"
            )
            return True, msg

        else:
            # 30–62%: golden zone
            fib_label = ""
            if 30 <= retrace_pct <= 38.2:
                fib_label = "~38.2% Fib"
            elif 38.2 < retrace_pct <= 50:
                fib_label = "~50% Fib"
            elif 50 < retrace_pct <= 62:
                fib_label = "~61.8% Fib (golden)"

            msg = (
                f"PULLBACK: {retrace_pct:.1f}% retrace from {pump_pct:.1f}% pump "
                f"— golden zone ✅ {fib_label}"
            )
            return True, msg

    except Exception as exc:
        msg = f"PULLBACK: Error ({exc}) — allowing ✅"
        logger.warning(f"Pullback quality check failed for {symbol}: {exc}", exc_info=True)
        return True, msg
