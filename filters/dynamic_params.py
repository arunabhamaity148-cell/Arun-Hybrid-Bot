"""
filters/dynamic_params.py — Adaptive Filter Thresholds + ATR-Based SL/TP
Arunabha Hybrid Bot v1.0

দুটো problem solve করে:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. DYNAMIC SL/TP (ATR-based)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
তোমার problem: "trade against এ চলে যায়"
কারণ: Fixed % SL — volatile market এ too tight, quiet market এ too loose।

Solution: ATR (Average True Range) দেখে SL adjust।
  ATR = coin এর average daily movement
  Volatile coin → SL wider (noise এ hit না করার জন্য)
  Quiet coin    → SL tighter (capital protect)

Formula:
  SL distance = grab_level_distance (base)
  কিন্তু minimum = 1.5 × ATR
  এবং maximum = 3.5 × ATR

Result: SL আর false stop-out হবে না।
        TP ও ATR দিয়ে realistic হবে।

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. ADAPTIVE FILTER THRESHOLDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Market regime দেখে filter thresholds বদলায়।
  Bull market  → MIN_RR relax (2.0), বেশি signal
  Bear market  → MIN_RR strict (3.0), কম signal কিন্তু quality
  Sideways     → Extra filters, noise কমায়
"""

import logging
from dataclasses import dataclass
from typing import Optional

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)


@dataclass
class DynamicParams:
    # ATR-adjusted levels
    atr_value:      float           # current ATR (14-period)
    atr_multiplier: float           # volatility label
    volatility:     str             # "HIGH" / "MEDIUM" / "LOW"

    # Adjusted SL/TP
    original_sl:    float
    original_tp1:   float
    original_tp2:   float
    adjusted_sl:    float           # ATR-aware SL
    adjusted_tp1:   float           # ATR-aware TP1
    adjusted_tp2:   float           # ATR-aware TP2
    sl_adjusted:    bool            # True = SL was changed
    rr_adjusted:    float           # new RR after adjustment

    # Adaptive thresholds for this signal
    effective_min_rr: float         # config.MIN_RR_RATIO বা adjusted
    rr_relaxed:       bool          # True = threshold was relaxed
    rr_tightened:     bool          # True = threshold was tightened

    def telegram_line(self) -> str:
        parts = []
        if self.sl_adjusted:
            parts.append(
                f"• ATR SL: {self.original_sl:.6g} → {self.adjusted_sl:.6g} "
                f"[{self.volatility} vol, ATR={self.atr_value:.4g}]"
            )
        if self.rr_relaxed:
            parts.append(f"• Min RR relaxed: {self.effective_min_rr:.1f} (bull market)")
        elif self.rr_tightened:
            parts.append(f"• Min RR tightened: {self.effective_min_rr:.1f} (bear market)")
        return "\n".join(parts) if parts else ""


async def _get_atr(symbol: str, period: int = 14) -> Optional[float]:
    """ATR calculate করো Binance/Delta candle data থেকে।"""
    cache_key = f"atr:{symbol}:{period}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    try:
        if getattr(config, "USE_DELTA_DATA", False):
            try:
                from data.delta_client import delta
                df = await delta.get_klines(symbol, "1h", limit=period + 5)
                if df is not None and not df.empty and len(df) >= period:
                    atr = _calc_atr(df, period)
                    await cache.set(cache_key, atr, ttl=300)
                    return atr
            except Exception:
                pass

        from data.binance_client import binance
        df = await binance.get_klines(symbol, "1h", limit=period + 5)
        if df is not None and not df.empty and len(df) >= period:
            atr = _calc_atr(df, period)
            await cache.set(cache_key, atr, ttl=300)
            return atr

    except Exception as exc:
        logger.debug(f"ATR fetch failed for {symbol}: {exc}")

    return None


def _calc_atr(df, period: int = 14) -> float:
    """Wilder's ATR calculation।"""
    import numpy as np

    highs  = df["high"].astype(float).values
    lows   = df["low"].astype(float).values
    closes = df["close"].astype(float).values

    tr_list = []
    for i in range(1, len(highs)):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i-1])
        lc = abs(lows[i] - closes[i-1])
        tr_list.append(max(hl, hc, lc))

    if len(tr_list) < period:
        return sum(tr_list) / len(tr_list) if tr_list else 0.0

    # Wilder's smoothing
    atr = sum(tr_list[:period]) / period
    for tr in tr_list[period:]:
        atr = (atr * (period - 1) + tr) / period

    return atr


def _classify_volatility(atr: float, price: float) -> tuple[str, float]:
    """ATR % of price দেখে volatility classify করো।"""
    if price <= 0:
        return "MEDIUM", 1.0

    atr_pct = atr / price * 100  # ATR as % of price

    if atr_pct >= 3.5:
        return "HIGH",   2.5    # wide SL needed
    elif atr_pct >= 1.5:
        return "MEDIUM", 2.0    # normal SL
    else:
        return "LOW",    1.5    # tight SL OK


def _adjust_sl_tp(
    direction:     str,
    entry:         float,
    original_sl:   float,
    original_tp1:  float,
    original_tp2:  float,
    atr:           float,
    volatility:    str,
    atr_multiplier: float,
) -> tuple[float, float, float, bool]:
    """
    ATR দেখে SL/TP adjust করো।
    Returns: adjusted_sl, adjusted_tp1, adjusted_tp2, was_adjusted
    """
    if atr <= 0 or entry <= 0:
        return original_sl, original_tp1, original_tp2, False

    min_sl_dist = atr * 1.5   # minimum SL distance = 1.5 ATR
    max_sl_dist = atr * 3.5   # maximum SL distance = 3.5 ATR

    if direction == "LONG":
        orig_sl_dist = entry - original_sl
        new_sl_dist  = max(min_sl_dist, min(max_sl_dist, orig_sl_dist))
        adjusted_sl  = entry - new_sl_dist

        # TP proportional to new SL
        rr1 = 1.5
        rr2 = 3.0
        adjusted_tp1 = entry + (new_sl_dist * rr1)
        adjusted_tp2 = entry + (new_sl_dist * rr2)

    else:  # SHORT
        orig_sl_dist = original_sl - entry
        new_sl_dist  = max(min_sl_dist, min(max_sl_dist, orig_sl_dist))
        adjusted_sl  = entry + new_sl_dist

        rr1 = 1.5
        rr2 = 3.0
        adjusted_tp1 = entry - (new_sl_dist * rr1)
        adjusted_tp2 = entry - (new_sl_dist * rr2)

    was_adjusted = abs(adjusted_sl - original_sl) / entry > 0.001  # >0.1% change

    return adjusted_sl, adjusted_tp1, adjusted_tp2, was_adjusted


def _get_adaptive_rr(regime_phase: str, btc_regime: str) -> tuple[float, bool, bool]:
    """
    Market regime দেখে MIN_RR threshold adjust করো।
    Returns: effective_min_rr, rr_relaxed, rr_tightened
    """
    base_rr = config.MIN_RR_RATIO  # default 2.5

    # Bull regime → relax RR (বেশি signal পাবো)
    if regime_phase in ("MARKUP", "ACCUMULATION") and "BULL" in btc_regime.upper():
        return max(2.0, base_rr - 0.3), True, False

    # Bear regime → tighten RR (quality over quantity)
    elif regime_phase in ("MARKDOWN", "DISTRIBUTION") or "BEAR" in btc_regime.upper():
        return min(3.5, base_rr + 0.5), False, True

    # Neutral
    return base_rr, False, False


async def get_dynamic_params(
    symbol:        str,
    direction:     str,
    entry:         float,
    original_sl:   float,
    original_tp1:  float,
    original_tp2:  float,
    regime_phase:  str = "UNKNOWN",
    btc_regime:    str = "NEUTRAL",
) -> DynamicParams:
    """
    Main function — ATR-based SL/TP + adaptive thresholds।
    engine.py তে signal pass হলে call হবে।
    """
    if not getattr(config, "DYNAMIC_PARAMS_ENABLED", True):
        base_rr = config.MIN_RR_RATIO
        return DynamicParams(
            atr_value=0, atr_multiplier=2.0, volatility="MEDIUM",
            original_sl=original_sl, original_tp1=original_tp1, original_tp2=original_tp2,
            adjusted_sl=original_sl, adjusted_tp1=original_tp1, adjusted_tp2=original_tp2,
            sl_adjusted=False,
            rr_adjusted=abs(original_sl - entry) / entry if entry > 0 else 0,
            effective_min_rr=base_rr, rr_relaxed=False, rr_tightened=False,
        )

    # Get ATR
    atr = await _get_atr(symbol)

    if not atr or atr <= 0:
        # ATR নেই — original values রাখো
        eff_rr, relaxed, tightened = _get_adaptive_rr(regime_phase, btc_regime)
        orig_rr = abs(entry - original_sl) / abs(entry - original_sl) * (
            abs(original_tp2 - entry) / abs(original_sl - entry)
        ) if abs(original_sl - entry) > 0 else 0

        return DynamicParams(
            atr_value=0, atr_multiplier=2.0, volatility="MEDIUM",
            original_sl=original_sl, original_tp1=original_tp1, original_tp2=original_tp2,
            adjusted_sl=original_sl, adjusted_tp1=original_tp1, adjusted_tp2=original_tp2,
            sl_adjusted=False, rr_adjusted=orig_rr,
            effective_min_rr=eff_rr, rr_relaxed=relaxed, rr_tightened=tightened,
        )

    # Classify volatility
    volatility, atr_mult = _classify_volatility(atr, entry)

    # Adjust SL/TP
    adj_sl, adj_tp1, adj_tp2, sl_adj = _adjust_sl_tp(
        direction, entry, original_sl, original_tp1, original_tp2,
        atr, volatility, atr_mult
    )

    # New RR
    sl_dist = abs(entry - adj_sl)
    tp_dist = abs(adj_tp2 - entry)
    new_rr  = tp_dist / sl_dist if sl_dist > 0 else 0

    # Adaptive RR threshold
    eff_rr, relaxed, tightened = _get_adaptive_rr(regime_phase, btc_regime)

    logger.debug(
        f"DynamicParams {symbol}: ATR={atr:.4g} Vol={volatility} "
        f"SL {original_sl:.4g}→{adj_sl:.4g} RR_thresh={eff_rr:.1f}"
    )

    return DynamicParams(
        atr_value=atr,
        atr_multiplier=atr_mult,
        volatility=volatility,
        original_sl=original_sl,
        original_tp1=original_tp1,
        original_tp2=original_tp2,
        adjusted_sl=adj_sl,
        adjusted_tp1=adj_tp1,
        adjusted_tp2=adj_tp2,
        sl_adjusted=sl_adj,
        rr_adjusted=new_rr,
        effective_min_rr=eff_rr,
        rr_relaxed=relaxed,
        rr_tightened=tightened,
    )
