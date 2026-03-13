"""
filters/btc_1h_bias.py — Filter F1B: BTC 1h Trend Bias

F1 (btc_regime.py) 4h chart দেখে big picture trend বোঝে।
F1B (এই filter) 1h chart দেখে short-term momentum বোঝে।

Logic:
  BTC 1h এর last 3 candle দেখো:
    - 3টা bullish (close > open) → LONG bias → SHORT block
    - 3টা bearish (close < open) → SHORT bias → LONG block
    - Mixed → neutral → উভয় allow

  Additional check — 1h EMA9 vs EMA21:
    EMA9 > EMA21 + momentum = strong BULL
    EMA9 < EMA21 + momentum = strong BEAR

  Hard block শুধু strong + consistent movement এ।
  Minor retracement candles এ block করে না।

কেন F1 থেকে আলাদা:
  F1 = 4h দিয়ে macro regime (BULL/BEAR/NEUTRAL)
  F1B = 1h দিয়ে current momentum — 4h BULL হলেও 1h তে short-term pullback থাকতে পারে
  একসাথে: macro + micro alignment confirm করে
"""

import logging
from typing import Tuple

import pandas as pd
import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


async def check_btc_1h_bias(direction: str) -> Tuple[bool, str]:
    """
    Returns (passed, log_message).

    Strong 1h bearish momentum → LONG blocked
    Strong 1h bullish momentum → SHORT blocked
    Neutral/mixed → both allowed
    """
    if not config.BTC_1H_BIAS_ENABLED:
        return True, "BTC_1H_BIAS: disabled ✅"

    try:
        df = await binance.get_klines("BTCUSDT", "1h", limit=30)

        if df.empty or len(df) < 10:
            return True, "BTC_1H_BIAS: insufficient data — allowing ✅"

        close = df["close"]
        open_ = df["open"]

        # Last 3 completed candles (exclude last which may be forming)
        last3_close = close.iloc[-4:-1].values
        last3_open = open_.iloc[-4:-1].values
        last3_bull = sum(1 for c, o in zip(last3_close, last3_open) if c > o)
        last3_bear = sum(1 for c, o in zip(last3_close, last3_open) if c < o)

        # EMA check
        ema9 = _ema(close, 9).iloc[-1]
        ema21 = _ema(close, 21).iloc[-1]
        ema_bull = ema9 > ema21
        ema_bear = ema9 < ema21

        # Price vs EMA21
        current_price = close.iloc[-1]
        price_above_ema = current_price > ema21
        price_below_ema = current_price < ema21

        # Strong bear: 3/3 bearish candles + EMA bear + price below EMA
        strong_bear = (last3_bear == 3 and ema_bear and price_below_ema)
        # Strong bull: 3/3 bullish candles + EMA bull + price above EMA
        strong_bull = (last3_bull == 3 and ema_bull and price_above_ema)

        # Moderate signals (2/3 candles + EMA alignment)
        mod_bear = (last3_bear >= 2 and ema_bear)
        mod_bull = (last3_bull >= 2 and ema_bull)

        btc_price_str = f"{current_price:.0f}"
        ema_str = f"EMA9:{ema9:.0f} EMA21:{ema21:.0f}"
        candle_str = f"↑{last3_bull}/↓{last3_bear} last 3 candles"

        if strong_bear and direction == "LONG":
            msg = (
                f"BTC_1H_BIAS: STRONG BEAR ({candle_str}, {ema_str}) — "
                f"LONG blocked ❌"
            )
            return False, msg

        if strong_bull and direction == "SHORT":
            msg = (
                f"BTC_1H_BIAS: STRONG BULL ({candle_str}, {ema_str}) — "
                f"SHORT blocked ❌"
            )
            return False, msg

        if mod_bear and direction == "LONG":
            msg = (
                f"BTC_1H_BIAS: BEARISH momentum ({candle_str}, {ema_str}) — "
                f"LONG caution ⚠️ (allowed)"
            )
            return True, msg

        if mod_bull and direction == "SHORT":
            msg = (
                f"BTC_1H_BIAS: BULLISH momentum ({candle_str}, {ema_str}) — "
                f"SHORT caution ⚠️ (allowed)"
            )
            return True, msg

        bias = "BULL" if last3_bull > last3_bear else ("BEAR" if last3_bear > last3_bull else "NEUTRAL")
        msg = (
            f"BTC_1H_BIAS: {bias} ({candle_str}, {ema_str}) — "
            f"{direction} aligned ✅"
        )
        return True, msg

    except Exception as exc:
        logger.warning(f"BTC 1h bias check failed: {exc}")
        return True, f"BTC_1H_BIAS: error ({exc}) — allowing ✅"
