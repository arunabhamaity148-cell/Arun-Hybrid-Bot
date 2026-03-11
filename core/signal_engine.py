"""
core/signal_engine.py — Signal Engine for Arunabha Hybrid Bot v1.0
Runs all filters in sequence for a given pair + direction.

Filter chain (11 steps):
  F1  BTC Regime          — hard block LONG in bear
  F2  Liquidity Grab      — swing wick hunt (15m)
  F3  CHoCH               — structure break confirm
  F4  FVG Multi-TF        — 15m + 1h confluence (UPGRADED)
  F4B Pullback Quality    — 30–62% Fibonacci retracement (NEW)
  F4C Pump Age            — pump must be < 2hr old (NEW)
  F4D Relative Volume     — 2-layer 1h + 15m vol check (NEW)
  F4E Sell Pressure       — pullback candle quality, detects distribution (NEW)
  F5  Volume Confirm      — CHoCH candle 2x avg
  F6  EMA Trend           — 1h EMA21 alignment
  F7  RR Validation       — real RR >= 2.5

New filters (4B/4C/4D) run AFTER FVG but BEFORE Volume Confirm.
They are skipped for core pairs where applicable (see config).
Failing 4B/4C/4D returns NO SIGNAL with specific reason logged.
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
from filters.pullback_quality import check_pullback_quality
from filters.pump_age import check_pump_age
from filters.relative_volume import check_relative_volume
from filters.sell_pressure import check_sell_pressure
from filters.volume_confirm import check_volume_confirm
from filters.ema_trend import check_ema_trend
from filters.rr_validator import check_rr_validator

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    filter_id: str       # e.g. "1", "4B", "4C"
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
    multitf_confluence: bool = False   # True if 15m + 1h FVG both aligned

    def filter_log_lines(self) -> list[str]:
        lines = []
        for f in self.filters:
            icon = "✅" if f.passed else "❌"
            lines.append(f"  {icon} F{f.filter_id} {f.message}")
        if not self.has_signal and self.skip_reason:
            lines.append(f"  ⏭️  Skipped remaining filters")
            lines.append(f"  📝 Result: NO SIGNAL — {self.skip_reason}")
        elif self.has_signal:
            confluence_tag = " [MULTI-TF ✨]" if self.multitf_confluence else ""
            lines.append(f"  📝 Result: ✨ SIGNAL GENERATED — {self.direction}{confluence_tag}")
        return lines


class SignalEngine:

    async def evaluate(
        self,
        symbol: str,
        direction: str,
        news_mode: bool = False,
        is_gainer: bool = False,
        is_trending: bool = False,
    ) -> SignalResult:
        """
        Run full filter chain for symbol + direction.

        is_gainer: True if pair came from gainer list (stricter vol thresholds)
        is_trending: True if pair from CoinGecko trending (pump age + pullback apply)
        is_core: True if pair is in CORE_PAIRS (some filters skipped)
        """
        result = SignalResult(symbol=symbol, direction=direction, has_signal=False)
        is_core = symbol in config.CORE_PAIRS
        is_dynamic = is_gainer or is_trending  # non-core dynamic pair

        # ── F1: BTC Regime ────────────────────────────────────────────────────
        passed, msg = await check_btc_regime(direction)
        result.filters.append(FilterResult("1", "BTC_REGIME", passed, msg))
        if not passed:
            result.skip_reason = "BTC regime blocked"
            return result

        # ── F2: Liquidity Grab ────────────────────────────────────────────────
        passed, msg, grab_level, grab_candles_ago = await check_liquidity_grab(symbol, direction)
        result.filters.append(FilterResult("2", "LIQ_GRAB", passed, msg))
        if not passed:
            result.skip_reason = "no liquidity grab setup"
            return result
        result.grab_level = grab_level

        # ── F3: CHoCH ─────────────────────────────────────────────────────────
        passed, msg, choch_level = await check_choch(symbol, direction, grab_candles_ago)
        result.filters.append(FilterResult("3", "CHOCH", passed, msg))
        if not passed:
            result.skip_reason = "CHoCH not confirmed"
            return result
        result.choch_level = choch_level

        # ── F4: FVG Multi-TF (UPGRADED) ───────────────────────────────────────
        try:
            current_price = await binance.get_price(symbol)
        except Exception:
            current_price = None

        passed, msg, fvg_low, fvg_high = await check_fvg(symbol, direction, current_price)
        result.filters.append(FilterResult("4", "FVG_MULTITF", passed, msg))

        # Detect if multi-TF confluence was found (for Telegram message)
        result.multitf_confluence = "MULTI-TF CONFLUENCE" in msg

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

        # ── F4B: Pullback Quality (NEW — dynamic pairs only) ──────────────────
        # Core pairs skip automatically inside the function (config.PULLBACK_SKIP_CORE_PAIRS)
        # For dynamic pairs this is a hard filter
        passed, msg = await check_pullback_quality(
            symbol, direction, current_price, is_core_pair=is_core
        )
        result.filters.append(FilterResult("4B", "PULLBACK", passed, msg))
        if not passed:
            result.skip_reason = "pullback not in golden zone (30–62%)"
            return result

        # ── F4C: Pump Age (NEW — dynamic pairs only) ──────────────────────────
        # Only meaningful for gainer/trending coins
        # Core pairs skip automatically inside the function
        passed, msg = await check_pump_age(
            symbol, direction, is_core_pair=is_core
        )
        result.filters.append(FilterResult("4C", "PUMP_AGE", passed, msg))
        if not passed:
            result.skip_reason = "pump too old (> 2hr) — late entry risk"
            return result

        # ── F4D: Relative Volume Score (NEW) ──────────────────────────────────
        # is_gainer = True applies stricter 2.0x thresholds
        # For core pairs: standard 1.5x/1.8x thresholds used
        passed, msg = await check_relative_volume(
            symbol, direction, is_gainer=is_gainer
        )
        result.filters.append(FilterResult("4D", "RELVOL", passed, msg))
        if not passed:
            result.skip_reason = "relative volume too low — no real accumulation"
            return result

        # ── F4E: Sell Pressure Check (NEW) ───────────────────────────────────
        # Checks if pullback candles show distribution (high vol + big red bodies)
        # vs healthy retracement (low vol + small bodies = sellers are weak)
        # Skipped for core pairs automatically (config.SELL_PRESSURE_SKIP_CORE_PAIRS)
        passed, msg = await check_sell_pressure(
            symbol, direction, is_core_pair=is_core
        )
        result.filters.append(FilterResult("4E", "SELL_PRESSURE", passed, msg))
        if not passed:
            result.skip_reason = "sell pressure too high — distribution pattern detected"
            return result

        # ── F5: Volume Confirmation (CHoCH candle) ────────────────────────────
        passed, msg = await check_volume_confirm(
            symbol, direction, news_mode=news_mode, grab_candles_ago=grab_candles_ago
        )
        result.filters.append(FilterResult("5", "VOLUME", passed, msg))
        if not passed:
            result.skip_reason = "weak volume on CHoCH candle"
            return result

        # ── F6: EMA Trend ─────────────────────────────────────────────────────
        passed, msg, ema21 = await check_ema_trend(symbol, direction)
        result.filters.append(FilterResult("6", "EMA_TREND", passed, msg))
        if not passed:
            result.skip_reason = "EMA trend not aligned"
            return result

        # ── F7: RR Validation ─────────────────────────────────────────────────
        if result.fvg_low and result.fvg_high:
            entry = current_price if current_price else (result.fvg_low + result.fvg_high) / 2
        elif result.fvg_optional_miss and choch_level:
            entry = current_price if current_price else choch_level
        elif current_price:
            entry = current_price
        else:
            entry = 0

        if entry == 0 or grab_level is None:
            result.filters.append(FilterResult("7", "RR", False, "RR: Cannot compute — no entry or grab level ❌"))
            result.skip_reason = "RR calculation error"
            return result

        passed, msg, levels = check_rr_validator(direction, entry, grab_level)
        result.filters.append(FilterResult("7", "RR", passed, msg))
        if not passed:
            result.skip_reason = f"RR below minimum {config.MIN_RR_RATIO}"
            return result

        # ── All filters passed ────────────────────────────────────────────────
        result.has_signal = True
        result.entry = entry
        result.sl = levels["sl"]
        result.tp1 = levels["tp1"]
        result.tp2 = levels["tp2"]
        result.rr = levels["rr"]
        result.sl_pct = levels["sl_pct"]

        confluence_tag = " [MULTI-TF]" if result.multitf_confluence else ""
        logger.info(
            f"✨ SIGNAL: {symbol} {direction}{confluence_tag} | "
            f"RR {levels['rr']:.1f} | Entry {entry:.8g}"
        )
        return result


signal_engine = SignalEngine()
