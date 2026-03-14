"""
core/position_sizing.py — Position Sizing Calculator

তোমার fixed parameters:
  Capital per trade: ₹5,000 INR (always)
  Leverage: 15x–20x
  Exchange: Delta Exchange

How it works:
  1. Signal score দেখো → recommended leverage decide করো
  2. ₹5,000 × leverage = total position value (INR)
  3. INR → USD convert করো (live rate থেকে)
  4. USD ÷ entry price = contract quantity
  5. SL distance থেকে actual INR risk calculate করো

Leverage rules (score-based):
  Score 80+  → 20x (high conviction, max leverage)
  Score 65-79 → 17x (good setup)
  Score 50-64 → 15x (moderate, minimum leverage)
  Score <50  → SKIP (bot signal এ trade নাও, কিন্তু এটা weak)

Risk per trade (always ₹5,000 margin):
  20x leverage → ₹1,00,000 position → SL 1% = ₹1,000 loss max
  15x leverage → ₹75,000 position  → SL 1% = ₹750 loss max

⚠️ WARNING: High leverage = high risk।
  Always use the SL provided by the signal। Never remove SL।
"""

import logging
from dataclasses import dataclass
from typing import Optional
import config

logger = logging.getLogger(__name__)

# ── Constants — config.py থেকে পড়া হয়, এখানে change করবে না ─────────────────
CAPITAL_PER_TRADE_INR = config.CAPITAL_PER_TRADE_INR   # default ₹5,000
MIN_LEVERAGE          = config.LEVERAGE_MIN             # default 15x
MAX_LEVERAGE          = config.LEVERAGE_MAX             # default 20x
USD_TO_INR_FALLBACK   = 83.5     # fallback rate if live fetch fails


@dataclass
class PositionPlan:
    # Input
    symbol:        str
    direction:     str
    entry_price:   float
    sl_price:      float
    tp1_price:     float
    tp2_price:     float
    signal_score:  int
    rr:            float

    # Calculated
    leverage:      int   = 0
    margin_inr:    float = 0.0
    position_inr:  float = 0.0
    position_usd:  float = 0.0
    quantity:      float = 0.0     # contracts / coins
    sl_distance_pct: float = 0.0
    max_loss_inr:  float = 0.0
    tp1_profit_inr:float = 0.0
    tp2_profit_inr:float = 0.0
    usd_rate:      float = 0.0
    skip_trade:    bool  = False
    skip_reason:   str   = ""

    def as_telegram_section(self) -> str:
        """Telegram signal message এ add করার জন্য"""
        if self.skip_trade:
            return (
                f"\n💰 <b>Position Sizing:</b>\n"
                f"⚠️ Score {self.signal_score}/100 — {self.skip_reason}\n"
                f"Margin: ₹{CAPITAL_PER_TRADE_INR:,} fixed\n"
                f"Leverage: Not recommended for this setup"
            )

        direction_emoji = "🟢" if self.direction == "LONG" else "🔴"

        score_lev = (
            "🔥 MAX (score 80+)" if self.leverage == MAX_LEVERAGE else
            "✅ HIGH (score 65+)" if self.leverage == 17 else
            "⚠️ MIN (score 50+)"
        )

        return (
            f"\n💰 <b>Position Sizing (Delta Exchange):</b>\n"
            f"• Margin: <b>₹{self.margin_inr:,.0f}</b> | "
            f"Leverage: <b>{self.leverage}x</b> {score_lev}\n"
            f"• Position: ₹{self.position_inr:,.0f} "
            f"(${self.position_usd:,.2f} @ ₹{self.usd_rate:.1f}/$)\n"
            f"• Quantity: <b>{self.quantity:.4g}</b> {self.symbol.replace('USDT','')}\n"
            f"• SL Distance: {self.sl_distance_pct:.2f}%\n"
            f"• Max Loss: <b>₹{self.max_loss_inr:,.0f}</b> "
            f"({self.max_loss_inr/self.margin_inr*100:.1f}% of margin)\n"
            f"• TP1 Profit: ₹{self.tp1_profit_inr:,.0f} "
            f"| TP2 Profit: <b>₹{self.tp2_profit_inr:,.0f}</b>\n"
            f"• Expected RR: {self.rr:.1f}:1\n\n"
            f"📋 <b>Delta Entry Steps:</b>\n"
            f"1. {self.symbol.replace('USDT','USD')} Perpetual খোলো\n"
            f"2. Leverage → {self.leverage}x set করো\n"
            f"3. Margin → ₹{self.margin_inr:,.0f} দাও\n"
            f"4. {direction_emoji} {self.direction} @ "
            f"<code>{self.entry_price:.6g}</code>\n"
            f"5. SL → <code>{self.sl_price:.6g}</code> (must set!)\n"
            f"6. TP1 → <code>{self.tp1_price:.6g}</code> (50% close)\n"
            f"7. TP2 → <code>{self.tp2_price:.6g}</code> (50% close)"
        )

    def as_console_summary(self) -> str:
        if self.skip_trade:
            return f"  💰 SIZING: SKIP — {self.skip_reason}"
        return (
            f"  💰 SIZING: {self.leverage}x | "
            f"₹{self.position_inr:,.0f} pos | "
            f"Qty: {self.quantity:.4g} | "
            f"Max loss: ₹{self.max_loss_inr:.0f}"
        )


async def _get_usd_inr_rate() -> float:
    """
    Live USD/INR rate fetch।
    Free API — no key needed।
    Falls back to 83.5 if unavailable।
    """
    import aiohttp
    from data.cache_manager import cache

    cached = await cache.get("usd_inr_rate")
    if cached:
        return cached

    try:
        url = "https://api.exchangerate-api.com/v4/latest/USD"
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5)
        ) as sess:
            async with sess.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rate = float(data["rates"]["INR"])
                    await cache.set("usd_inr_rate", rate, ttl=3600.0)
                    return rate
    except Exception as exc:
        logger.debug(f"USD/INR rate fetch failed: {exc}")

    return USD_TO_INR_FALLBACK


def _get_leverage(signal_score: int) -> tuple[int, bool, str]:
    """
    Score দেখে leverage decide করো।
    Returns (leverage, skip, reason)
    """
    if signal_score >= 80:
        return MAX_LEVERAGE, False, ""        # 20x
    elif signal_score >= 65:
        return 17, False, ""                  # 17x
    elif signal_score >= 50:
        return MIN_LEVERAGE, False, ""        # 15x
    else:
        return 0, True, f"Score {signal_score}/100 too low — setup weak"


async def calculate_position(
    symbol:       str,
    direction:    str,
    entry_price:  float,
    sl_price:     float,
    tp1_price:    float,
    tp2_price:    float,
    signal_score: int,
    rr:           float,
) -> PositionPlan:
    """
    Signal এর জন্য complete position plan তৈরি করো।
    Always uses ₹5,000 margin।
    """
    plan = PositionPlan(
        symbol=symbol, direction=direction,
        entry_price=entry_price, sl_price=sl_price,
        tp1_price=tp1_price, tp2_price=tp2_price,
        signal_score=signal_score, rr=rr,
        margin_inr=CAPITAL_PER_TRADE_INR,
    )

    leverage, skip, skip_reason = _get_leverage(signal_score)

    if skip:
        plan.skip_trade  = True
        plan.skip_reason = skip_reason
        return plan

    # Live USD/INR rate
    usd_rate = await _get_usd_inr_rate()

    # Position calculation
    position_inr = CAPITAL_PER_TRADE_INR * leverage
    position_usd = position_inr / usd_rate
    quantity     = position_usd / entry_price

    # SL distance
    if direction == "LONG":
        sl_dist_pct = (entry_price - sl_price) / entry_price * 100
        tp1_dist_pct = (tp1_price - entry_price) / entry_price * 100
        tp2_dist_pct = (tp2_price - entry_price) / entry_price * 100
    else:
        sl_dist_pct  = (sl_price - entry_price) / entry_price * 100
        tp1_dist_pct = (entry_price - tp1_price) / entry_price * 100
        tp2_dist_pct = (entry_price - tp2_price) / entry_price * 100

    # P&L in INR
    max_loss_inr   = position_inr * (sl_dist_pct / 100)
    tp1_profit_inr = position_inr * (tp1_dist_pct / 100)
    tp2_profit_inr = position_inr * (tp2_dist_pct / 100)

    plan.leverage        = leverage
    plan.position_inr    = position_inr
    plan.position_usd    = position_usd
    plan.quantity        = round(quantity, 6)
    plan.sl_distance_pct = round(sl_dist_pct, 3)
    plan.max_loss_inr    = round(max_loss_inr, 2)
    plan.tp1_profit_inr  = round(tp1_profit_inr, 2)
    plan.tp2_profit_inr  = round(tp2_profit_inr, 2)
    plan.usd_rate        = usd_rate

    logger.info(
        f"Position [{symbol} {direction}]: "
        f"{leverage}x | ₹{position_inr:,.0f} | "
        f"Qty:{quantity:.4g} | Max loss:₹{max_loss_inr:.0f}"
    )

    return plan
