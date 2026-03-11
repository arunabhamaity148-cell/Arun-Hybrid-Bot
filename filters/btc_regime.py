"""
filters/btc_regime.py — Filter 1: BTC Market Regime
Hard-blocks LONG signals when BTC is in strong bear trend.
"""

import logging
import pandas as pd
import numpy as np
from typing import Tuple

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series]:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    dm_plus = high.diff()
    dm_minus = -low.diff()
    dm_plus = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0.0)
    dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0.0)

    di_plus = 100 * dm_plus.rolling(period).mean() / atr
    di_minus = 100 * dm_minus.rolling(period).mean() / atr
    dx = (100 * (di_plus - di_minus).abs() / (di_plus + di_minus)).replace([np.inf, -np.inf], 0)
    adx_series = dx.rolling(period).mean()
    return adx_series, di_plus - di_minus


async def check_btc_regime(direction: str) -> Tuple[bool, str]:
    try:
        df_4h = await binance.get_klines("BTCUSDT", "4h", limit=250)
        df_1h = await binance.get_klines("BTCUSDT", "1h", limit=50)

        if df_4h.empty or len(df_4h) < 200:
            msg = "BTC_REGIME: Insufficient data — allowing by default"
            return True, msg

        ema9_4h = _ema(df_4h["close"], 9).iloc[-1]
        ema21_4h = _ema(df_4h["close"], 21).iloc[-1]
        ema200_4h = _ema(df_4h["close"], 200).iloc[-1]
        adx_series, di_diff = _adx(df_4h)
        adx_val = adx_series.iloc[-1]
        di_direction = di_diff.iloc[-1]

        strong_bear = (
            ema9_4h < ema21_4h
            and ema21_4h < ema200_4h
            and adx_val > 25
            and di_direction < 0
        )

        adx_rounded = round(adx_val, 1)
        ema_desc = "bearish" if ema9_4h < ema21_4h < ema200_4h else (
            "bullish" if ema9_4h > ema21_4h > ema200_4h else "mixed"
        )
        regime = "BEAR" if strong_bear else ("BULL" if ema9_4h > ema21_4h else "NEUTRAL")

        if strong_bear and direction == "LONG":
            msg = f"BTC_REGIME: BEAR (ADX:{adx_rounded}, EMA:{ema_desc}) — LONG blocked ❌"
            return False, msg

        msg = f"BTC_REGIME: {regime} (ADX:{adx_rounded}, EMA:{ema_desc}) — {direction} allowed ✅"
        return True, msg

    except Exception as exc:
        msg = f"BTC_REGIME: Error ({exc}) — allowing by default"
        logger.warning(msg)
        return True, msg
