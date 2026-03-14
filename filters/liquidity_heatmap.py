"""
filters/liquidity_heatmap.py — Liquidation Cluster TP Adjustment
Arunabha Hybrid Bot v1.0

Top traders এর strategy: Random TP না — liquidation cluster এ TP set করো।
Price সবসময় সবচেয়ে বেশি liquidation যেখানে সেখানে যেতে চায় (stop hunt)।

Data Source: Binance Futures Open Interest + Order Book
  - Open Interest হিসেব: কোন level এ সবচেয়ে বেশি position আটকে আছে
  - Order Book depth: কোন price level এ বড় wall আছে
  - Combination: liquidation magnet zones বের করা

Implementation (free, no external API):
  1. Current funding rate + OI থেকে leverage estimate
  2. Order book এর large bid/ask walls = liquidation levels
  3. TP1/TP2 এই levels এর কাছাকাছি হলে → adjust করো

Result:
  adjusted_tp1, adjusted_tp2 — original TP এর কাছের liquidation magnet
  liq_zone_label — nearest cluster এর description
  tp_adjusted — True হলে Telegram এ note দেখাবে

TOD (Time of Day) window caution এখানেই handle করা হয়।
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

import pytz
import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# ── TOD Config ────────────────────────────────────────────────────────────────
# NY Open এর প্রথম ১৫ মিনিট — fake breakout zone
# IST 19:30 = NY 09:00
TOD_CAUTION_START = 19 * 60 + 30   # 19:30 IST in minutes
TOD_CAUTION_END   = 19 * 60 + 45   # 19:45 IST in minutes

# Order book wall detection — কত % বড় wall কে significant মানবো
OB_WALL_THRESHOLD_PCT = 0.15        # total book এর ১৫%+ = significant wall


@dataclass
class HeatmapResult:
    symbol:        str
    direction:     str

    # TP adjustment
    original_tp1:  float
    original_tp2:  float
    adjusted_tp1:  float
    adjusted_tp2:  float
    tp_adjusted:   bool             # True = TP was snapped to liq cluster
    adjustment_pct: float           # % difference between original and adjusted

    # Liquidation zones found
    liq_zones:     list[float] = field(default_factory=list)   # price levels
    nearest_zone:  Optional[float] = None
    liq_label:     str = "NONE"     # "MAJOR_CLUSTER" / "MINOR_CLUSTER" / "NONE"

    # TOD
    tod_caution:   bool = False     # True = NY open fake breakout window
    tod_message:   str  = ""

    # Score bonus
    score:         int  = 0         # 0-5 pts

    def telegram_section(self) -> str:
        lines = []

        if self.tod_caution:
            lines.append(f"\n⏰ <b>TOD Alert:</b> ⚠️ NY Open fake breakout window (19:30-19:45 IST)")
            lines.append(f"   Entry wait করো — 19:45 এর পরে confirm হলে নাও")

        if self.tp_adjusted:
            lines.append(
                f"\n🎯 <b>TP Adjusted (Liq Cluster):</b>\n"
                f"   TP1: {self.original_tp1:.6g} → {self.adjusted_tp1:.6g}\n"
                f"   TP2: {self.original_tp2:.6g} → {self.adjusted_tp2:.6g}\n"
                f"   [{self.liq_label} — price magnet detected]"
            )

        return "\n".join(lines) if lines else ""


def _check_tod_caution() -> tuple[bool, str]:
    """NY Open এর প্রথম ১৫ মিনিট fake breakout zone check।"""
    now_ist = datetime.now(IST)
    current_minutes = now_ist.hour * 60 + now_ist.minute

    if TOD_CAUTION_START <= current_minutes <= TOD_CAUTION_END:
        return True, f"NY Open window {now_ist.strftime('%H:%M')} IST — fake breakout risk"

    return False, ""


async def _get_order_book_walls(symbol: str, direction: str, current_price: float) -> list[float]:
    """
    Order book থেকে large walls detect করো।
    LONG direction: ask side এ বড় wall = resistance = potential TP target
    SHORT direction: bid side এ বড় wall = support = potential TP target
    """
    cache_key = f"ob_walls:{symbol}:{direction}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    walls = []
    try:
        from data.binance_client import binance
        ob = await binance.get_order_book(symbol, limit=20)

        if not ob:
            return []

        # Choose relevant side
        if direction == "LONG":
            levels = ob.get("asks", [])  # resistance levels above price
        else:
            levels = ob.get("bids", [])  # support levels below price

        if not levels:
            return []

        # Total volume on this side
        total_vol = sum(float(qty) for _, qty in levels)
        if total_vol == 0:
            return []

        # Find significant walls (>15% of total book)
        for price_str, qty_str in levels:
            price = float(price_str)
            qty   = float(qty_str)
            if qty / total_vol >= OB_WALL_THRESHOLD_PCT:
                walls.append(price)

        await cache.set(cache_key, walls, ttl=30)
        return walls

    except Exception as exc:
        logger.debug(f"Order book fetch failed for {symbol}: {exc}")
        return []


async def _get_oi_levels(symbol: str) -> list[float]:
    """
    Binance Open Interest history থেকে high OI price levels।
    High OI = many positions = potential liquidation cascade।
    """
    cache_key = f"oi_levels:{symbol}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    levels = []
    try:
        import httpx
        # Binance OI history endpoint — 30min intervals, last 10 data points
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        params = {
            "symbol": symbol,
            "period": "30m",
            "limit":  10,
        }

        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            data = resp.json()

        if not data:
            return []

        # Find period with highest OI — that price level is a magnet
        max_oi_entry = max(data, key=lambda x: float(x.get("sumOpenInterest", 0)))
        # The timestamp maps to a price — we use the current price context
        # Simple heuristic: return max OI value as signal strength (not price)
        oi_values = [float(d.get("sumOpenInterest", 0)) for d in data]
        oi_change = (oi_values[-1] - oi_values[0]) / oi_values[0] if oi_values[0] > 0 else 0

        # Return OI change as signal (stored as special sentinel)
        await cache.set(cache_key, [oi_change], ttl=120)
        return [oi_change]

    except Exception as exc:
        logger.debug(f"OI history fetch failed for {symbol}: {exc}")
        return []


def _snap_tp_to_wall(
    original_tp: float,
    walls: list[float],
    direction: str,
    current_price: float,
    snap_tolerance_pct: float = 0.8,
) -> tuple[float, bool]:
    """
    Original TP এর কাছে কোনো significant wall আছে কিনা check করে।
    আছে এবং ±0.8% এর মধ্যে হলে wall এ snap করে।
    """
    if not walls:
        return original_tp, False

    best_wall = None
    best_dist = float("inf")

    for wall in walls:
        dist_pct = abs(wall - original_tp) / original_tp * 100
        if dist_pct <= snap_tolerance_pct and dist_pct < best_dist:
            # Wall must be in the right direction from current price
            if direction == "LONG" and wall > current_price:
                best_wall = wall
                best_dist = dist_pct
            elif direction == "SHORT" and wall < current_price:
                best_wall = wall
                best_dist = dist_pct

    if best_wall is not None:
        return best_wall, True

    return original_tp, False


async def get_heatmap_result(
    symbol:        str,
    direction:     str,
    current_price: float,
    original_tp1:  float,
    original_tp2:  float,
) -> HeatmapResult:
    """
    Main function — TP adjustment + TOD caution।
    Signal score এ +0-5 bonus যোগ হবে।
    """
    # ── TOD Check ─────────────────────────────────────────────────────────────
    tod_caution, tod_msg = _check_tod_caution()

    # ── Order Book Walls ──────────────────────────────────────────────────────
    walls = await _get_order_book_walls(symbol, direction, current_price)

    # ── OI Levels ─────────────────────────────────────────────────────────────
    oi_data = await _get_oi_levels(symbol)
    oi_change = oi_data[0] if oi_data else 0.0

    # ── Snap TP to nearest wall ───────────────────────────────────────────────
    adj_tp1, tp1_snapped = _snap_tp_to_wall(original_tp1, walls, direction, current_price)
    adj_tp2, tp2_snapped = _snap_tp_to_wall(original_tp2, walls, direction, current_price)

    tp_adjusted = tp1_snapped or tp2_snapped
    adj_pct = abs(adj_tp1 - original_tp1) / original_tp1 * 100 if original_tp1 > 0 else 0

    # ── Liq Zone Label ────────────────────────────────────────────────────────
    if len(walls) >= 2:
        liq_label = "MAJOR_CLUSTER"
    elif len(walls) == 1:
        liq_label = "MINOR_CLUSTER"
    else:
        liq_label = "NONE"

    # ── Score ─────────────────────────────────────────────────────────────────
    score = 0
    if not tod_caution:
        score += 2  # no fake breakout window = safer
    if tp_adjusted:
        score += 2  # TP aligned with liq cluster = better exit
    if oi_change > 0.05:
        score += 1  # OI increasing = more fuel

    score = min(5, score)

    logger.debug(
        f"Heatmap {symbol}: Walls={walls[:3]} TP_adj={tp_adjusted} "
        f"TOD={tod_caution} Score=+{score}"
    )

    return HeatmapResult(
        symbol=symbol,
        direction=direction,
        original_tp1=original_tp1,
        original_tp2=original_tp2,
        adjusted_tp1=adj_tp1,
        adjusted_tp2=adj_tp2,
        tp_adjusted=tp_adjusted,
        adjustment_pct=adj_pct,
        liq_zones=walls,
        nearest_zone=walls[0] if walls else None,
        liq_label=liq_label,
        tod_caution=tod_caution,
        tod_message=tod_msg,
        score=score,
    )
