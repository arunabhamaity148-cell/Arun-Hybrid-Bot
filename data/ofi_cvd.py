"""
data/ofi_cvd.py — Order Flow Imbalance (OFI) + Cumulative Volume Delta (CVD)
Arunabha Hybrid Bot v1.0 — Advanced Signal Scoring

দুটো technique যেগুলো retail trader সাধারণত use করে না:

OFI (Order Flow Imbalance):
  Candle দেখে না — bid/ask volume absorption দেখে।
  বড় player কোন দিকে accumulate করছে সেটা বোঝায়।
  Formula: (buy_vol - sell_vol) / total_vol  → -1.0 to +1.0
  Source: Binance aggTrades REST endpoint (free, no key)

CVD (Cumulative Volume Delta):
  Price direction vs volume direction divergence detect করে।
  Price উঠছে + CVD নামছে = hidden distribution (SHORT bias)
  Price নামছে + CVD উঠছে = hidden accumulation (LONG bias)
  Source: Same aggTrades data

Implementation:
  aggTrades এ প্রতিটা trade এর isBuyerMaker field আছে।
  isBuyerMaker=True  → seller initiated (sell volume)
  isBuyerMaker=False → buyer initiated (buy volume)
  এটা candle volume এর চেয়ে অনেক বেশি accurate।

Cache: 60 seconds (aggTrades REST call)
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

# ── Cache TTL ─────────────────────────────────────────────────────────────────
_OFI_CACHE_SECONDS = 60


@dataclass
class OFICVDResult:
    symbol:        str
    direction:     str          # "LONG" or "SHORT"

    # OFI
    ofi_ratio:     float        # -1.0 to +1.0 (positive = buy pressure)
    ofi_label:     str          # "STRONG_BUY" / "BUY" / "NEUTRAL" / "SELL" / "STRONG_SELL"
    ofi_score:     int          # 0-10 bonus points

    # CVD
    cvd_delta:     float        # cumulative buy_vol - sell_vol over lookback
    cvd_divergence: bool        # True = price vs CVD diverging (caution)
    cvd_label:     str          # "CONFIRMING" / "DIVERGING" / "NEUTRAL"
    cvd_score:     int          # 0-8 bonus points

    # Funding Divergence
    funding_divergence: bool    # True = price direction vs funding direction diverge
    funding_div_label:  str     # "ORGANIC" / "OVERLEVERAGED" / "NEUTRAL"
    funding_div_score:  int     # 0-7 bonus points

    # Total bonus
    total_bonus:   int          # ofi + cvd + funding_div (max 25)
    caution_flags: list[str]    # warning messages for Telegram

    def telegram_section(self) -> str:
        lines = ["\n⚡ <b>Order Flow Analysis:</b>"]

        # OFI
        ofi_bar = _make_bar(self.ofi_ratio, range_min=-1.0, range_max=1.0, width=5)
        lines.append(f"• OFI: {ofi_bar} {self.ofi_label} ({self.ofi_ratio:+.2f})")

        # CVD
        if self.cvd_divergence:
            lines.append(f"• CVD: ⚠️ DIVERGING — price vs volume mismatch")
        else:
            lines.append(f"• CVD: ✅ {self.cvd_label}")

        # Funding divergence
        if self.funding_div_label == "ORGANIC":
            lines.append(f"• Flow: ✅ Organic move (funding aligned)")
        elif self.funding_div_label == "OVERLEVERAGED":
            lines.append(f"• Flow: ⚠️ Overleveraged — funding vs price diverge")

        # Bonus
        if self.total_bonus > 0:
            lines.append(f"• Bonus: +{self.total_bonus} pts")

        return "\n".join(lines)

    def console_summary(self) -> str:
        flags = f" ⚠️ {', '.join(self.caution_flags)}" if self.caution_flags else ""
        return (
            f"  ⚡ OFI: {self.ofi_label} ({self.ofi_ratio:+.2f}) | "
            f"CVD: {self.cvd_label} | "
            f"Flow: {self.funding_div_label} | "
            f"Bonus: +{self.total_bonus}{flags}"
        )


def _make_bar(value: float, range_min: float, range_max: float, width: int = 5) -> str:
    """Simple progress bar for OFI visualization."""
    normalized = (value - range_min) / (range_max - range_min)
    filled = round(normalized * width)
    filled = max(0, min(width, filled))
    mid = width // 2
    bar = ""
    for i in range(width):
        if i < mid:
            bar += "🟥" if i < filled else "⬜"
        elif i == mid:
            bar += "⬜"
        else:
            bar += "🟩" if i < filled else "⬜"
    return bar


async def _fetch_agg_trades(symbol: str, limit: int = 500) -> list[dict]:
    """
    Binance Futures aggTrades REST endpoint — free, no key needed.
    Returns list of {price, qty, isBuyerMaker, time}
    """
    cache_key = f"aggtrades:{symbol}:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    try:
        import httpx
        url = f"https://fapi.binance.com/fapi/v1/aggTrades"
        params = {"symbol": symbol, "limit": limit}

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            trades = resp.json()

        await cache.set(cache_key, trades, ttl=_OFI_CACHE_SECONDS)
        return trades

    except Exception as exc:
        logger.warning(f"aggTrades fetch failed for {symbol}: {exc}")
        return []


def _calculate_ofi(trades: list[dict], direction: str) -> tuple[float, str, int]:
    """
    Order Flow Imbalance calculation।
    isBuyerMaker=False → buyer initiated (taker buy) = bullish flow
    isBuyerMaker=True  → seller initiated (taker sell) = bearish flow
    """
    if not trades:
        return 0.0, "NEUTRAL", 5  # neutral score when no data

    buy_vol  = sum(float(t["q"]) for t in trades if not t["m"])  # m = isBuyerMaker
    sell_vol = sum(float(t["q"]) for t in trades if t["m"])
    total_vol = buy_vol + sell_vol

    if total_vol == 0:
        return 0.0, "NEUTRAL", 5

    ofi_ratio = (buy_vol - sell_vol) / total_vol  # -1.0 to +1.0

    # Label
    if ofi_ratio >= 0.35:
        label = "STRONG_BUY"
    elif ofi_ratio >= 0.15:
        label = "BUY"
    elif ofi_ratio <= -0.35:
        label = "STRONG_SELL"
    elif ofi_ratio <= -0.15:
        label = "SELL"
    else:
        label = "NEUTRAL"

    # Score (direction-aware)
    if direction == "LONG":
        if label == "STRONG_BUY":  score = 10
        elif label == "BUY":       score = 7
        elif label == "NEUTRAL":   score = 5
        elif label == "SELL":      score = 2
        else:                       score = 0  # STRONG_SELL
    else:  # SHORT
        if label == "STRONG_SELL": score = 10
        elif label == "SELL":       score = 7
        elif label == "NEUTRAL":   score = 5
        elif label == "BUY":       score = 2
        else:                       score = 0  # STRONG_BUY

    return ofi_ratio, label, score


def _calculate_cvd(trades: list[dict], current_price: float, direction: str) -> tuple[float, bool, str, int]:
    """
    Cumulative Volume Delta — price direction vs volume direction divergence।

    Hidden distribution: Price ↑↑ + CVD ↓↓ = Smart money selling into retail buying
    Hidden accumulation: Price ↓↓ + CVD ↑↑ = Smart money buying into retail selling
    """
    if not trades or len(trades) < 20:
        return 0.0, False, "NEUTRAL", 4

    # Calculate CVD over all trades
    first_price = float(trades[0]["p"])
    last_price  = float(trades[-1]["p"])
    price_change = last_price - first_price  # positive = price went up

    buy_vol  = sum(float(t["q"]) for t in trades if not t["m"])
    sell_vol = sum(float(t["q"]) for t in trades if t["m"])
    cvd_delta = buy_vol - sell_vol  # positive = net buying

    # Divergence detection
    diverging = False
    if price_change > 0 and cvd_delta < 0:
        # Price up but net selling — hidden distribution
        diverging = True
        label = "DIVERGING"
    elif price_change < 0 and cvd_delta > 0:
        # Price down but net buying — hidden accumulation
        diverging = True
        label = "DIVERGING"
    elif abs(price_change) < 0.001 * current_price:
        label = "NEUTRAL"  # price barely moved
    else:
        label = "CONFIRMING"

    # Score (direction-aware)
    if diverging:
        # CVD diverging against direction = caution
        score = 0
    elif label == "CONFIRMING":
        # Price and volume confirm = bonus
        score = 8
    else:
        score = 4  # neutral

    return cvd_delta, diverging, label, score


def _calculate_funding_divergence(
    direction: str,
    funding_rate: float,
    funding_label: str,
    price_change_pct: float,
) -> tuple[bool, str, int]:
    """
    Funding Rate Divergence — price move vs funding alignment।

    Organic move:     Price ↑ + Funding neutral/slightly positive = real buying
    Overleveraged:    Price ↑ + Funding rapidly increasing = crowded longs = reversal risk
    Contrarian edge:  Price ↑ + Funding negative = shorts paying longs = squeeze incoming
    """
    if funding_label == "DISABLED":
        return False, "NEUTRAL", 4

    organic     = False
    overleveraged = False

    if direction == "LONG":
        if funding_rate < 0:
            # Negative funding for LONG = shorts paying = high conviction
            organic = True
            label = "ORGANIC"
            score = 7
        elif funding_label == "NEUTRAL" and price_change_pct > 0:
            # Price up + neutral funding = organic accumulation
            organic = True
            label = "ORGANIC"
            score = 6
        elif funding_label in ("EXTREME_LONG",) and price_change_pct > 2:
            # Price up a lot + extreme long funding = overleveraged
            overleveraged = True
            label = "OVERLEVERAGED"
            score = 0
        else:
            label = "NEUTRAL"
            score = 3

    else:  # SHORT
        if funding_rate > 0:
            # Positive funding for SHORT = longs paying = high conviction short
            organic = True
            label = "ORGANIC"
            score = 7
        elif funding_label == "NEUTRAL" and price_change_pct < 0:
            label = "ORGANIC"
            score = 6
        elif funding_label in ("EXTREME_SHORT",) and price_change_pct < -2:
            overleveraged = True
            label = "OVERLEVERAGED"
            score = 0
        else:
            label = "NEUTRAL"
            score = 3

    return overleveraged, label, score


async def get_ofi_cvd(
    symbol:       str,
    direction:    str,
    current_price: float,
    funding_rate:  float = 0.0,
    funding_label: str   = "NEUTRAL",
    price_change_24h: float = 0.0,
) -> OFICVDResult:
    """
    Main function — OFI + CVD + Funding Divergence calculate করে।
    signal_engine তে score booster হিসেবে use হবে।
    """
    caution_flags = []

    # Fetch aggTrades
    trades = await _fetch_agg_trades(symbol, limit=500)

    # ── OFI ──────────────────────────────────────────────────────────────────
    ofi_ratio, ofi_label, ofi_score = _calculate_ofi(trades, direction)

    if ofi_label in ("STRONG_SELL",) and direction == "LONG":
        caution_flags.append("OFI bearish")
    elif ofi_label in ("STRONG_BUY",) and direction == "SHORT":
        caution_flags.append("OFI bullish")

    # ── CVD ──────────────────────────────────────────────────────────────────
    cvd_delta, cvd_divergence, cvd_label, cvd_score = _calculate_cvd(
        trades, current_price, direction
    )

    if cvd_divergence:
        caution_flags.append("CVD diverging")

    # ── Funding Divergence ────────────────────────────────────────────────────
    overleveraged, funding_div_label, funding_div_score = _calculate_funding_divergence(
        direction, funding_rate, funding_label, price_change_24h
    )

    if overleveraged:
        caution_flags.append("Overleveraged")

    # ── Total Bonus ───────────────────────────────────────────────────────────
    total_bonus = min(25, ofi_score + cvd_score + funding_div_score)

    logger.debug(
        f"OFI/CVD {symbol} {direction}: OFI={ofi_label}({ofi_ratio:+.2f}) "
        f"CVD={cvd_label} FundDiv={funding_div_label} Bonus=+{total_bonus}"
    )

    return OFICVDResult(
        symbol=symbol,
        direction=direction,
        ofi_ratio=ofi_ratio,
        ofi_label=ofi_label,
        ofi_score=ofi_score,
        cvd_delta=cvd_delta,
        cvd_divergence=cvd_divergence,
        cvd_label=cvd_label,
        cvd_score=cvd_score,
        funding_divergence=overleveraged,
        funding_div_label=funding_div_label,
        funding_div_score=funding_div_score,
        total_bonus=total_bonus,
        caution_flags=caution_flags,
    )
