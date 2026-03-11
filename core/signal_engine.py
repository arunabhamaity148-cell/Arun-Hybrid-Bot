"""
core/signal_engine.py — Signal Engine for Arunabha Hybrid Bot v1.0
Runs all 7 filters in sequence for a given pair + direction.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import config
from data.binance_client import binance
from filters.btc_regime import check_btc_regime
from filters.liquidity_grab import check_liquidity_grab
from filters.choch import check_choch
from filters.fvg import check_fvg
from filters.volume_confirm import check_volume_confirm
from filters.ema_trend import check_ema_trend
from filters.rr_validator import check_rr_validator

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    filter_id: int
    name: str
    passed: bool
    message: str


@dataclass
class SignalResult:
    symbol: str
    direction: str
    has_signal: bool
    filters: list[FilterResult] = field(default_factory=list)
    skip_reason: Optional[str] = None

    entry: Optional[float] = None
    sl: Optional[float] = None
    tp1: Optional[float] = None
    tp2: Optional[float] = None
    rr: Optional[float] = None
    sl_pct: Optional[float] = None
    grab_level: Optional[float] = None
    choch_level: Optional[float] = None
    fvg_low: Optional[float] = None
    fvg_high: Optional[float] = None
    fvg_optional_miss: bool = False

    def filter_log_lines(self) -> list[str]:
        lines = []
        for f in self.filters:
            icon = "✅" if f.passed else "❌"
            lines.append(f"  {icon} F{f.filter_id} {f.message}")
        if not self.has_signal and self.skip_reason:
            lines.append(f"  ⏭️  Skipped remaining filters")
            lines.append(f"  📝 Result: NO SIGNAL — {self.skip_reason}")
        elif self.has_signal:
            lines.append(f"  📝 Result: ✨ SIGNAL GENERATED — {self.direction}")
        return lines


class SignalEngine:

    async def evaluate(self, symbol: str, direction: str, news_mode: bool = False) -> SignalResult:
        result = SignalResult(symbol=symbol, direction=direction, has_signal=False)

        # F1: BTC Regime
        passed, msg = await check_btc_regime(direction)
        result.filters.append(FilterResult(1, "BTC_REGIME", passed, msg))
        if not passed:
            result.skip_reason = "BTC regime blocked"
            return result

        # F2: Liquidity Grab
        passed, msg, grab_level, grab_candles_ago = await check_liquidity_grab(symbol, direction)
        result.filters.append(FilterResult(2, "LIQ_GRAB", passed, msg))
        if not passed:
            result.skip_reason = "no liquidity grab setup"
            return result
        result.grab_level = grab_level

        # F3: CHoCH
        passed, msg, choch_level = await check_choch(symbol, direction, grab_candles_ago)
        result.filters.append(FilterResult(3, "CHOCH", passed, msg))
        if not passed:
            result.skip_reason = "CHoCH not confirmed"
            return result
        result.choch_level = choch_level

        # F4: FVG
        try:
            current_price = await binance.get_price(symbol)
        except Exception:
            current_price = None

        passed, msg, fvg_low, fvg_high = await check_fvg(symbol, direction, current_price)
        result.filters.append(FilterResult(4, "FVG", passed, msg))

        if not passed:
            if config.FVG_OPTIONAL:
                result.fvg_low = None
                result.fvg_high = None
                result.fvg_optional_miss = True
            else:
                result.skip_reason = "waiting for FVG pullback" if fvg_low else "no FVG found"
                return result
        else:
            result.fvg_low = fvg_low
            result.fvg_high = fvg_high
            result.fvg_optional_miss = False

        # F5: Volume Confirmation
        passed, msg = await check_volume_confirm(
            symbol, direction, news_mode=news_mode, grab_candles_ago=grab_candles_ago
        )
        result.filters.append(FilterResult(5, "VOLUME", passed, msg))
        if not passed:
            result.skip_reason = "weak volume on CHoCH candle"
            return result

        # F6: EMA Trend
        passed, msg, ema21 = await check_ema_trend(symbol, direction)
        result.filters.append(FilterResult(6, "EMA_TREND", passed, msg))
        if not passed:
            result.skip_reason = "EMA trend not aligned"
            return result

        # F7: RR Validation
        if result.fvg_low and result.fvg_high:
            entry = current_price if current_price else (result.fvg_low + result.fvg_high) / 2
        elif result.fvg_optional_miss and choch_level:
            entry = current_price if current_price else choch_level
        elif current_price:
            entry = current_price
        else:
            entry = 0

        if entry == 0 or grab_level is None:
            result.filters.append(FilterResult(7, "RR", False, "RR: Cannot compute — no entry or grab level ❌"))
            result.skip_reason = "RR calculation error"
            return result

        passed, msg, levels = check_rr_validator(direction, entry, grab_level)
        result.filters.append(FilterResult(7, "RR", passed, msg))
        if not passed:
            result.skip_reason = f"RR below minimum {config.MIN_RR_RATIO}"
            return result

        result.has_signal = True
        result.entry = entry
        result.sl = levels["sl"]
        result.tp1 = levels["tp1"]
        result.tp2 = levels["tp2"]
        result.rr = levels["rr"]
        result.sl_pct = levels["sl_pct"]

        logger.info(f"✨ SIGNAL: {symbol} {direction} | RR {levels['rr']:.1f} | Entry {entry:.8g}")
        return result


signal_engine = SignalEngine()
