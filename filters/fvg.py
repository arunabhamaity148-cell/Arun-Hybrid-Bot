"""
filters/fvg.py — Filter 4: Fair Value Gap (FVG) Detection — Multi-TF Version
Primary: 15m FVG — entry zone detection
Secondary: 1h FVG — confluence check (higher conviction)

Logic:
  - 15m FVG must exist AND price must be entering it (mandatory)
  - 1h FVG checked separately for confluence
  - If 1h FVG also aligns → high conviction signal
  - If 1h FVG missing → MULTITF_FVG_REQUIRED=True mane block, False mane warn only
  - This replaces the old single-TF 15m only check

Why 1h FVG matters for gainer/trending coins:
  - 15m FVG = noise level, filled quickly in volatile coins
  - 1h FVG = institutional order block, price respects it more reliably
  - Both aligning = smart money + retail confluence = much higher hit rate
"""

import logging
import pandas as pd
from typing import Tuple, Optional

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)


def _find_fvg(df: pd.DataFrame, direction: str, lookback: int) -> Optional[Tuple[float, float]]:
    """
    Scan last `lookback` candles for a fair value gap.
    Returns (fvg_low, fvg_high) of the most recent unfilled FVG, or None.
    """
    n = len(df)
    max_look = min(lookback, n - 2)

    for i in range(n - 1, n - max_look - 1, -1):
        if i < 2:
            break
        c1 = df.iloc[i - 2]   # candle before the impulse
        c3 = df.iloc[i]        # candle after the impulse

        if direction == "LONG":
            # Bullish FVG: gap between c1 high and c3 low
            fvg_low = c1["high"]
            fvg_high = c3["low"]
            if fvg_high > fvg_low:
                return (fvg_low, fvg_high)
        else:
            # Bearish FVG: gap between c3 high and c1 low
            fvg_high = c1["low"]
            fvg_low = c3["high"]
            if fvg_high > fvg_low:
                return (fvg_low, fvg_high)

    return None


def _price_in_fvg(fvg_low: float, fvg_high: float, current_price: float) -> bool:
    """Check if price is inside or within tolerance of entering FVG zone."""
    mid = (fvg_low + fvg_high) / 2
    tolerance = mid * config.FVG_ENTRY_TOLERANCE_PCT
    return (fvg_low - tolerance) <= current_price <= (fvg_high + tolerance)


def _fvg_overlap(
    fvg15_low: float, fvg15_high: float,
    fvg1h_low: float, fvg1h_high: float,
) -> bool:
    """
    Check if 15m FVG and 1h FVG zones overlap.
    Overlap = both timeframes agree on the same price area = high confluence.
    """
    return fvg15_low <= fvg1h_high and fvg1h_low <= fvg15_high


async def check_fvg(
    symbol: str,
    direction: str,
    current_price: Optional[float] = None,
) -> Tuple[bool, str, Optional[float], Optional[float]]:
    """
    Returns (passed, log_message, fvg_low, fvg_high).

    Step 1: Find 15m FVG — mandatory. Price must be entering zone.
    Step 2: Find 1h FVG — confluence check.
            If overlap → strong confluence tag.
            If no overlap → MULTITF_FVG_REQUIRED controls pass/fail.
    """
    try:
        # ── Step 1: 15m FVG (mandatory) ──────────────────────────────────────
        df_15m = await binance.get_klines(symbol, "15m", limit=50)
        if df_15m.empty or len(df_15m) < 5:
            return False, "FVG: Insufficient 15m data — skip ❌", None, None

        if current_price is None:
            current_price = float(df_15m["close"].iloc[-1])

        fvg_15m = _find_fvg(df_15m, direction, config.FVG_LOOKBACK)
        if fvg_15m is None:
            return False, "FVG: No 15m fair value gap found ❌", None, None

        fvg15_low, fvg15_high = fvg_15m
        if not _price_in_fvg(fvg15_low, fvg15_high, current_price):
            msg = (
                f"FVG: 15m zone {fvg15_low:.8g}–{fvg15_high:.8g} found "
                f"but price ({current_price:.8g}) not entering yet ❌"
            )
            return False, msg, None, None

        # ── Step 2: 1h FVG confluence check ──────────────────────────────────
        try:
            df_1h = await binance.get_klines(symbol, "1h", limit=config.FVG_1H_LOOKBACK + 5)
            fvg_1h = _find_fvg(df_1h, direction, config.FVG_1H_LOOKBACK) if not df_1h.empty else None
        except Exception:
            fvg_1h = None

        if fvg_1h is not None:
            fvg1h_low, fvg1h_high = fvg_1h
            overlap = _fvg_overlap(fvg15_low, fvg15_high, fvg1h_low, fvg1h_high)

            if overlap:
                # Best case: both TFs agree on same zone
                # Use intersection as tighter entry zone
                entry_low = max(fvg15_low, fvg1h_low)
                entry_high = min(fvg15_high, fvg1h_high)
                msg = (
                    f"FVG: ✨ MULTI-TF CONFLUENCE — "
                    f"15m({fvg15_low:.8g}–{fvg15_high:.8g}) + "
                    f"1h({fvg1h_low:.8g}–{fvg1h_high:.8g}) overlap, "
                    f"price ({current_price:.8g}) entering ✅✅"
                )
                return True, msg, entry_low, entry_high
            else:
                # 1h FVG exists but different zone — no overlap
                if config.MULTITF_FVG_REQUIRED:
                    msg = (
                        f"FVG: 15m zone found ({fvg15_low:.8g}–{fvg15_high:.8g}) "
                        f"but 1h FVG ({fvg1h_low:.8g}–{fvg1h_high:.8g}) no overlap "
                        f"— MULTITF_FVG_REQUIRED=True, skip ❌"
                    )
                    return False, msg, None, None
                else:
                    # Warn but pass — 15m alone is enough
                    msg = (
                        f"FVG: 15m zone ({fvg15_low:.8g}–{fvg15_high:.8g}), "
                        f"price entering ✅ | 1h zone different (no TF confluence ⚠️)"
                    )
                    return True, msg, fvg15_low, fvg15_high
        else:
            # No 1h FVG found at all
            if config.MULTITF_FVG_REQUIRED:
                msg = (
                    f"FVG: 15m zone ({fvg15_low:.8g}–{fvg15_high:.8g}) found "
                    f"but no 1h FVG — MULTITF_FVG_REQUIRED=True, skip ❌"
                )
                return False, msg, None, None
            else:
                msg = (
                    f"FVG: 15m zone ({fvg15_low:.8g}–{fvg15_high:.8g}), "
                    f"price entering ✅ | 1h FVG not found (single TF only ⚠️)"
                )
                return True, msg, fvg15_low, fvg15_high

    except Exception as exc:
        msg = f"FVG: Error ({exc}) — skip ❌"
        logger.warning(f"FVG check failed for {symbol}: {exc}")
        return False, msg, None, None
