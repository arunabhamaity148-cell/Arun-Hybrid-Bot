"""
data/cross_basis.py — Cross-Exchange Basis (Futures vs Spot)
Arunabha Hybrid Bot v1.0

Futures price vs Spot price এর gap দেখে market sentiment বোঝায়।

Basis = (Futures Price - Spot Price) / Spot Price × 100

Interpretation:
  Basis > +0.3%  = Overheated longs (futures premium too high)
                   → SHORT bias signal / LONG এ caution
  Basis < -0.3%  = Panic selling (futures discount = backwardation)
                   → LONG bias signal (contrarian) / SHORT এ caution
  Basis ±0.05%   = Neutral = organic move
  Basis +0.1~0.3% = Mild premium = healthy bull
  Basis -0.1~-0.3% = Mild discount = healthy bear

Data Sources:
  Futures price: Binance FAPI (already have this)
  Spot price:    Binance Spot API (free, no key)

Cache: 30 seconds
"""

import logging
from dataclasses import dataclass
from typing import Optional

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

_BASIS_CACHE_SECONDS = 30

# Symbol mapping: BTCUSDT (futures) → BTCUSDT (spot)
# Most pairs are same name — only exceptions listed
_FUTURES_TO_SPOT: dict[str, str] = {
    "BTCUSDT": "BTCUSDT",
    "ETHUSDT": "ETHUSDT",
    # Delta symbols (if used)
    "BTCUSD":  "BTCUSDT",
    "ETHUSD":  "ETHUSDT",
}


@dataclass
class CrossBasisResult:
    symbol:          str
    direction:       str
    futures_price:   float
    spot_price:      float
    basis_pct:       float      # (futures - spot) / spot * 100
    basis_label:     str        # OVERHEATED / PREMIUM / NEUTRAL / DISCOUNT / BACKWARDATION
    score:           int        # 0-5 bonus points
    caution:         Optional[str] = None    # caution message if any

    def telegram_line(self) -> str:
        if self.caution:
            return f"• Basis: ⚠️ {self.basis_pct:+.3f}% [{self.basis_label}] — {self.caution}"
        elif self.basis_label in ("PREMIUM", "DISCOUNT"):
            return f"• Basis: ✅ {self.basis_pct:+.3f}% [{self.basis_label}]"
        else:
            return f"• Basis: {self.basis_pct:+.3f}% [{self.basis_label}]"


async def _get_spot_price(symbol: str) -> Optional[float]:
    """Binance Spot API থেকে price নেওয়া — free, no key."""
    # Normalize symbol
    spot_sym = _FUTURES_TO_SPOT.get(symbol, symbol)
    # Remove 'PERP' suffix if present
    spot_sym = spot_sym.replace("PERP", "")

    cache_key = f"spot_price:{spot_sym}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    try:
        import httpx
        url = "https://api.binance.com/api/v3/ticker/price"
        params = {"symbol": spot_sym}

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 400:
                # Spot pair doesn't exist
                return None
            resp.raise_for_status()
            price = float(resp.json()["price"])

        await cache.set(cache_key, price, ttl=_BASIS_CACHE_SECONDS)
        return price

    except Exception as exc:
        logger.debug(f"Spot price fetch failed for {spot_sym}: {exc}")
        return None


async def _get_futures_price(symbol: str) -> Optional[float]:
    """Binance Futures price — already available via binance_client."""
    try:
        from data.binance_client import binance
        return await binance.get_price(symbol)
    except Exception:
        return None


def _classify_basis(basis_pct: float, direction: str) -> tuple[str, int, Optional[str]]:
    """
    Basis percentage → label + score + caution।
    Direction-aware: high basis bad for LONG, good for SHORT.
    """
    caution = None

    if basis_pct >= 0.5:
        label = "OVERHEATED"
        if direction == "LONG":
            score = 0
            caution = "Futures সব premium — overleveraged longs"
        else:
            score = 4  # SHORT এ good — longs will get squeezed

    elif basis_pct >= 0.15:
        label = "PREMIUM"
        if direction == "LONG":
            score = 3  # Mild caution
        else:
            score = 4

    elif basis_pct >= -0.05:
        label = "NEUTRAL"
        score = 5  # Best for any direction

    elif basis_pct >= -0.15:
        label = "DISCOUNT"
        if direction == "SHORT":
            score = 3
        else:
            score = 4  # LONG এ good — buying opportunity

    else:  # < -0.15
        label = "BACKWARDATION"
        if direction == "SHORT":
            score = 0
            caution = "Futures এ panic selling — extreme backwardation"
        else:
            score = 4  # LONG এ contrarian buy signal

    return label, score, caution


async def get_cross_basis(symbol: str, direction: str) -> CrossBasisResult:
    """
    Main function — Futures vs Spot basis calculate করে।
    Signal score এ +0-5 bonus যোগ হবে।
    """
    futures_price = await _get_futures_price(symbol)
    spot_price    = await _get_spot_price(symbol)

    # Fallback if can't fetch
    if not futures_price or not spot_price or spot_price == 0:
        return CrossBasisResult(
            symbol=symbol,
            direction=direction,
            futures_price=futures_price or 0,
            spot_price=spot_price or 0,
            basis_pct=0.0,
            basis_label="UNAVAILABLE",
            score=3,  # neutral assumption
            caution=None,
        )

    basis_pct = (futures_price - spot_price) / spot_price * 100
    label, score, caution = _classify_basis(basis_pct, direction)

    logger.debug(
        f"Cross-basis {symbol}: F={futures_price:.4g} S={spot_price:.4g} "
        f"Basis={basis_pct:+.3f}% [{label}] Score=+{score}"
    )

    return CrossBasisResult(
        symbol=symbol,
        direction=direction,
        futures_price=futures_price,
        spot_price=spot_price,
        basis_pct=basis_pct,
        basis_label=label,
        score=score,
        caution=caution,
    )
