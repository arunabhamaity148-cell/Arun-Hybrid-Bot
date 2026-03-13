"""
filters/volume_spike_guard.py — Filter F4G: Volume Spike Guard

যদি current candle এর volume, last 10 candle average এর 3x বেশি হয়,
তাহলে signal pause করো।

কেন pause করা উচিত:
  3x+ volume spike মানে কিছু বড় ঘটছে — news, whale move, liquidation cascade।
  এই মুহূর্তে price action unpredictable।
  তোমার liquidity grab + CHoCH setup হয়তো সঠিক,
  কিন্তু spike এর পরের candle উল্টো দিকে reversal করতে পারে।
  
  Better approach: spike এর পরে বসে থাকো, পরের scan এ দেখো।
  Spike settle হলে তখন signal valid।

vs F4D (relative_volume.py):
  F4D = volume থাকা ভালো কিনা check করে (2x+ = strong signal)
  F4G = volume অতিরিক্ত বেশি কিনা check করে (3x+ = pause)
  দুটো opposite উদ্দেশ্যে, একসাথে কাজ করে:
    F4D pass: volume আছে ✅
    F4G pass: volume অতিরিক্ত নয় ✅

Config:
  VOLUME_SPIKE_GUARD_ENABLED: True/False
  VOLUME_SPIKE_GUARD_MULTIPLIER: কতগুণ হলে pause (default 3.0)
  VOLUME_SPIKE_GUARD_LOOKBACK: কতটা candle average নেবে (default 10)
"""

import logging
from typing import Tuple

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


async def check_volume_spike_guard(symbol: str) -> Tuple[bool, str]:
    """
    Returns (passed, log_message).

    passed=True  → volume normal, proceed
    passed=False → volume spike detected, pause this signal
    """
    if not config.VOLUME_SPIKE_GUARD_ENABLED:
        return True, "VOL_SPIKE_GUARD: disabled ✅"

    try:
        lookback = config.VOLUME_SPIKE_GUARD_LOOKBACK + 2  # extra buffer
        df = await binance.get_klines(symbol, "15m", limit=lookback)

        if df.empty or len(df) < config.VOLUME_SPIKE_GUARD_LOOKBACK + 1:
            return True, "VOL_SPIKE_GUARD: insufficient data — allowing ✅"

        vol = df["volume"]

        # Current candle (last) vs average of previous N candles
        current_vol = vol.iloc[-1]
        avg_vol = vol.iloc[-(config.VOLUME_SPIKE_GUARD_LOOKBACK + 1):-1].mean()

        if avg_vol <= 0:
            return True, "VOL_SPIKE_GUARD: zero avg volume — allowing ✅"

        multiplier = current_vol / avg_vol
        threshold = config.VOLUME_SPIKE_GUARD_MULTIPLIER

        if multiplier >= threshold:
            msg = (
                f"VOL_SPIKE_GUARD: {multiplier:.1f}x spike detected "
                f"(>{threshold}x threshold) — signal paused ⏸️ "
                f"[wait for next scan]"
            )
            return False, msg

        elif multiplier >= threshold * 0.7:
            # Approaching threshold — warn but allow
            msg = (
                f"VOL_SPIKE_GUARD: {multiplier:.1f}x volume "
                f"(approaching {threshold}x limit) — caution ⚠️ (allowed)"
            )
            return True, msg

        else:
            msg = (
                f"VOL_SPIKE_GUARD: {multiplier:.1f}x volume — normal ✅"
            )
            return True, msg

    except Exception as exc:
        logger.warning(f"Volume spike guard failed for {symbol}: {exc}")
        return True, f"VOL_SPIKE_GUARD: error ({exc}) — allowing ✅"
