"""
core/signal_engine.py — Signal Engine for Arunabha Hybrid Bot v1.0
Priority 3 Update: Filter chain simplified + Signal Score added

Filter chain (optimized — 12 steps, 3 warn-only):
  F0   News Sentiment       — 4-source news check (block)
  F1   BTC Regime+1h        — 4h macro + 1h micro combined (block)
  F2   Liquidity Grab       — swing wick hunt 15m (block)
  F3   CHoCH                — 3-step structure break (block)
  F4   FVG Multi-TF         — 15m + 1h confluence (block)
  F4B  Pullback Quality     — Fibonacci zone (WARN ONLY — never blocks)
  F4C  Pump Age             — pump freshness (WARN ONLY — never blocks)
  F4D  Relative Volume      — 2-layer volume check (block)
  F4E  Sell Pressure        — distribution detection (block)
  F4F  Funding Rate         — crowd bias (block)
  F5   Volume Confirm       — CHoCH candle volume (WARN ONLY — never blocks)
  F6   EMA Trend            — 1h EMA21 alignment (block)
  F7   RR Validation        — RR >= 2.5 (block)

Removed:
  F1B  BTC 1h Bias          — merged into F1 (BTC Regime now checks both 4h+1h)
  F4G  Volume Spike Guard   — removed (contradicts F4D, adds noise)

Warn-only filters log the result but NEVER block the signal.
They contribute to signal_score instead.

Priority 2: Data source selection
  USE_DELTA_DATA=True → Delta Exchange candles used where possible
  Fallback to Binance if Delta unavailable
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pytz
import config
from filters.news_sentiment  import check_news_sentiment
from filters.btc_regime      import check_btc_regime
from filters.btc_1h_bias     import check_btc_1h_bias
from filters.liquidity_grab  import check_liquidity_grab
from filters.choch           import check_choch
from filters.fvg             import check_fvg
from filters.pullback_quality import check_pullback_quality
from filters.pump_age        import check_pump_age
from filters.relative_volume import check_relative_volume
from filters.sell_pressure   import check_sell_pressure
from filters.funding_rate    import check_funding_rate
from filters.volume_confirm  import check_volume_confirm
from filters.ema_trend       import check_ema_trend
from filters.rr_validator    import check_rr_validator

logger  = logging.getLogger(__name__)
IST     = pytz.timezone("Asia/Kolkata")


@dataclass
class FilterResult:
    filter_id: str
    name:      str
    passed:    bool
    message:   str
    warn_only: bool = False   # True = never blocks, only informs score


@dataclass
class SignalResult:
    symbol:    str
    direction: str
    has_signal: bool
    filters:   list[FilterResult] = field(default_factory=list)
    skip_reason: Optional[str]    = None

    entry:   Optional[float] = None
    sl:      Optional[float] = None
    tp1:     Optional[float] = None
    tp2:     Optional[float] = None
    rr:      Optional[float] = None
    sl_pct:  Optional[float] = None

    grab_level:    Optional[float] = None
    choch_level:   Optional[float] = None
    fvg_low:       Optional[float] = None
    fvg_high:      Optional[float] = None
    fvg_optional_miss:  bool  = False
    multitf_confluence: bool  = False

    funding_rate_pct: float = 0.0
    funding_label:    str   = "N/A"

    # Priority 4: Signal Score
    signal_score:     int   = 0
    score_breakdown:  dict  = field(default_factory=dict)

    def filter_log_lines(self) -> list[str]:
        lines = []
        for f in self.filters:
            if f.warn_only:
                icon = "⚠️" if not f.passed else "✅"
                tag  = " [warn-only]"
            else:
                icon = "✅" if f.passed else "❌"
                tag  = ""
            lines.append(f"  {icon} F{f.filter_id} {f.message}{tag}")

        if not self.has_signal and self.skip_reason:
            lines.append("  ⏭️  Skipped remaining filters")
            lines.append(f"  📝 NO SIGNAL — {self.skip_reason}")
        elif self.has_signal:
            confluence_tag = " [MULTI-TF ✨]" if self.multitf_confluence else ""
            lines.append(
                f"  📝 ✨ SIGNAL — {self.direction}{confluence_tag} | "
                f"Score: {self.signal_score}/100"
            )
        return lines




async def _get_current_price(symbol: str) -> Optional[float]:
    """
    Delta mark price → Binance last price fallback।
    Delta তে trade করলে Delta price বেশি accurate।
    """
    if getattr(config, "USE_DELTA_DATA", False):
        try:
            from data.delta_client import delta
            price = await delta.get_mark_price(symbol)
            if price:
                return price
        except Exception:
            pass

    try:
        from data.binance_client import binance
        return await binance.get_price(symbol)
    except Exception:
        return None




# ── Signal Score Calculator ───────────────────────────────────────────────────

def _calculate_signal_score(
    result:        "SignalResult",
    fg_val:        int,
    warn_results:  dict,
    ofi_bonus:     int = 0,
    basis_bonus:   int = 0,
    heatmap_bonus: int = 0,
    regime_bonus:  int = 0,   # Regime detection: +10 aligned, -5 against
    agent_bonus:   int = 0,   # Multi-agent: +8 PROCEED, -8 SKIP
    pattern_bonus: int = 0,   # Candle patterns: -5 to +8
) -> tuple[int, dict]:
    """
    Signal Score — 0 to 160।
    Base score: 0-100
    Advanced bonuses: 0-60

    Base Breakdown:
      RR quality     → 30 pts
      Multi-TF       → 20 pts
      Funding rate   → 15 pts
      Fear & Greed   → 15 pts
      Session        → 10 pts
      Warn filters   → 10 pts

    Advanced Bonuses:
      OFI + CVD + Funding Divergence → max 25 pts
      Cross-Exchange Basis           → max  5 pts
      Liquidity Heatmap + TOD        → max  5 pts
      Regime Detection               → -5 to +10 pts
      Multi-Agent Cross-Check        → -8 to +8 pts
      Candle Pattern Recognition     → -5 to +8 pts
    """
    score     = 0
    breakdown = {}

    # ── Base Score (0-100) ────────────────────────────────────────────────────

    # RR (30 points)
    rr = result.rr or 0
    if rr >= 4.0:
        rr_pts = 30
    elif rr >= 3.0:
        rr_pts = 24
    elif rr >= 2.5:
        rr_pts = 18
    else:
        rr_pts = 8
    score += rr_pts
    breakdown["RR"] = rr_pts

    # Multi-TF Confluence (20 points)
    conf_pts = 20 if result.multitf_confluence else 5
    score += conf_pts
    breakdown["MultiTF"] = conf_pts

    # Funding Rate (15 points)
    if result.funding_label == "NEUTRAL":
        fr_pts = 15
    elif result.funding_label in ("LONG_CAUTION", "SHORT_CAUTION"):
        fr_pts = 8
    elif result.funding_label == "DISABLED":
        fr_pts = 10
    else:
        fr_pts = 2  # extreme
    score += fr_pts
    breakdown["Funding"] = fr_pts

    # Fear & Greed (15 points)
    if 40 <= fg_val <= 65:
        fg_pts = 15
    elif 25 <= fg_val <= 75:
        fg_pts = 9
    elif 10 <= fg_val <= 90:
        fg_pts = 5
    else:
        fg_pts = 2
    score += fg_pts
    breakdown["FG"] = fg_pts

    # Session (10 points)
    ist_hour = datetime.now(IST).hour
    if 16 <= ist_hour <= 21:      # NY Open (IST 16-22)
        sess_pts = 10
    elif 13 <= ist_hour <= 16:    # London Open
        sess_pts = 8
    elif 9 <= ist_hour <= 13:     # Asia/London
        sess_pts = 5
    elif 7 <= ist_hour <= 9:
        sess_pts = 3
    else:
        sess_pts = 1
    score += sess_pts
    breakdown["Session"] = sess_pts

    # Warn-only filters (10 points)
    warn_pts = 0
    if warn_results.get("pullback_pass", True):
        warn_pts += 4
    if warn_results.get("pump_pass", True):
        warn_pts += 3
    if warn_results.get("vol_pass", True):
        warn_pts += 3
    score += warn_pts
    breakdown["WarnFilters"] = warn_pts

    base_score = min(100, max(0, score))

    # ── Advanced Bonuses ─────────────────────────────────────────────────────
    ofi_b     = min(25, max(0,   ofi_bonus))
    basis_b   = min(5,  max(0,   basis_bonus))
    heatmap_b = min(5,  max(0,   heatmap_bonus))
    regime_b  = min(10, max(-5,  regime_bonus))
    agent_b   = min(8,  max(-8,  agent_bonus))
    pattern_b = min(8,  max(-5,  pattern_bonus))
    total_bonus = ofi_b + basis_b + heatmap_b + regime_b + agent_b + pattern_b

    breakdown["OFI_Bonus"]     = ofi_b
    breakdown["Basis_Bonus"]   = basis_b
    breakdown["Heatmap_Bonus"] = heatmap_b
    breakdown["Regime_Bonus"]  = regime_b
    breakdown["Agent_Bonus"]   = agent_b
    breakdown["Pattern_Bonus"] = pattern_b
    breakdown["AdvBonus"]      = total_bonus

    final = base_score + total_bonus
    breakdown["Base"]  = base_score
    breakdown["Total"] = final

    return min(160, max(0, final)), breakdown


# ── Main Engine ───────────────────────────────────────────────────────────────

class SignalEngine:

    async def evaluate(
        self,
        symbol:      str,
        direction:   str,
        news_mode:   bool = False,
        is_gainer:   bool = False,
        is_trending: bool = False,
    ) -> SignalResult:

        result   = SignalResult(symbol=symbol, direction=direction, has_signal=False)
        is_core  = symbol in config.CORE_PAIRS

        # Warn-only filter results (for score calculation later)
        warn_results = {
            "pullback_pass": True,
            "pump_pass":     True,
            "vol_pass":      True,
        }

        # ── F0: News Sentiment ───────────────────────────────────────────────
        passed, msg = await check_news_sentiment(symbol, direction)
        result.filters.append(FilterResult("0", "NEWS", passed, msg))
        if not passed:
            result.skip_reason = "news sentiment against direction"
            return result

        # ── F1: BTC Regime (4h) ──────────────────────────────────────────────
        passed, msg = await check_btc_regime(direction)
        result.filters.append(FilterResult("1", "BTC_REGIME", passed, msg))
        if not passed:
            result.skip_reason = "BTC 4h regime blocked"
            return result

        # ── F1B: BTC 1h Bias — HARD BLOCK শুধু STRONG signal এ ─────────────
        # F1 এর সাথে রাখা হলো কিন্তু শুধু strong_bear/strong_bull block করে
        passed_1b, msg_1b = await check_btc_1h_bias(direction)
        result.filters.append(FilterResult("1B", "BTC_1H", passed_1b, msg_1b))
        if not passed_1b:
            result.skip_reason = "BTC 1h strong momentum against direction"
            return result

        # ── F2: Liquidity Grab ───────────────────────────────────────────────
        passed, msg, grab_level, grab_candles_ago = await check_liquidity_grab(
            symbol, direction
        )
        result.filters.append(FilterResult("2", "LIQ_GRAB", passed, msg))
        if not passed:
            result.skip_reason = "no liquidity grab setup"
            return result
        result.grab_level = grab_level

        # ── F3: CHoCH ────────────────────────────────────────────────────────
        passed, msg, choch_level = await check_choch(
            symbol, direction, grab_candles_ago
        )
        result.filters.append(FilterResult("3", "CHOCH", passed, msg))
        if not passed:
            result.skip_reason = "CHoCH not confirmed"
            return result
        result.choch_level = choch_level

        # ── Current Price (Delta → Binance fallback) ─────────────────────────
        current_price = await _get_current_price(symbol)

        # ── F4: FVG Multi-TF ─────────────────────────────────────────────────
        passed, msg, fvg_low, fvg_high = await check_fvg(
            symbol, direction, current_price
        )
        result.filters.append(FilterResult("4", "FVG_MULTITF", passed, msg))
        result.multitf_confluence = "MULTI-TF CONFLUENCE" in msg

        if not passed:
            if config.FVG_OPTIONAL:
                result.fvg_optional_miss = True
            else:
                result.skip_reason = "no FVG / waiting for pullback"
                return result
        else:
            result.fvg_low  = fvg_low
            result.fvg_high = fvg_high

        # ── F4B: Pullback Quality — WARN ONLY ────────────────────────────────
        pb_passed, pb_msg = await check_pullback_quality(
            symbol, direction, current_price, is_core_pair=is_core
        )
        result.filters.append(
            FilterResult("4B", "PULLBACK", pb_passed, pb_msg, warn_only=True)
        )
        warn_results["pullback_pass"] = pb_passed
        # NO return — warn only, never blocks

        # ── F4C: Pump Age — WARN ONLY ────────────────────────────────────────
        pa_passed, pa_msg = await check_pump_age(
            symbol, direction, is_core_pair=is_core
        )
        result.filters.append(
            FilterResult("4C", "PUMP_AGE", pa_passed, pa_msg, warn_only=True)
        )
        warn_results["pump_pass"] = pa_passed
        # NO return — warn only, never blocks

        # ── F4D: Relative Volume — BLOCKS ────────────────────────────────────
        passed, msg = await check_relative_volume(
            symbol, direction, is_gainer=is_gainer
        )
        result.filters.append(FilterResult("4D", "RELVOL", passed, msg))
        if not passed:
            result.skip_reason = "relative volume too low"
            return result

        # ── F4E: Sell Pressure — BLOCKS ──────────────────────────────────────
        passed, msg = await check_sell_pressure(
            symbol, direction, is_core_pair=is_core
        )
        result.filters.append(FilterResult("4E", "SELL_PRESSURE", passed, msg))
        if not passed:
            result.skip_reason = "distribution pattern detected"
            return result

        # ── F4F: Funding Rate — BLOCKS ───────────────────────────────────────
        if config.FUNDING_FILTER_ENABLED:
            passed, msg, fr_pct = await check_funding_rate(symbol, direction)
            result.filters.append(FilterResult("4F", "FUNDING", passed, msg))
            result.funding_rate_pct = fr_pct

            if fr_pct >= config.FUNDING_EXTREME_THRESHOLD:
                result.funding_label = "EXTREME_LONG"
            elif fr_pct >= config.FUNDING_HIGH_THRESHOLD:
                result.funding_label = "HIGH_LONG"
            elif fr_pct <= -config.FUNDING_EXTREME_THRESHOLD:
                result.funding_label = "EXTREME_SHORT"
            elif fr_pct <= -config.FUNDING_HIGH_THRESHOLD:
                result.funding_label = "HIGH_SHORT"
            elif fr_pct <= -config.FUNDING_HIGH_THRESHOLD / 2:
                result.funding_label = "SHORT_CAUTION"
            elif fr_pct >= config.FUNDING_HIGH_THRESHOLD / 2:
                result.funding_label = "LONG_CAUTION"
            else:
                result.funding_label = "NEUTRAL"

            if not passed:
                result.skip_reason = "funding too crowded"
                return result
        else:
            result.funding_label = "DISABLED"

        # NOTE: F4G (Volume Spike Guard) REMOVED
        # Reason: Contradicts F4D. F4D already ensures volume is present.
        # F4G was blocking signals with good volume. Removed per Priority 3.

        # ── F5: Volume Confirm — WARN ONLY ───────────────────────────────────
        vc_passed, vc_msg = await check_volume_confirm(
            symbol, direction, news_mode=news_mode,
            grab_candles_ago=grab_candles_ago
        )
        result.filters.append(
            FilterResult("5", "VOL_CONFIRM", vc_passed, vc_msg, warn_only=True)
        )
        warn_results["vol_pass"] = vc_passed
        # NO return — warn only

        # ── F6: EMA Trend — BLOCKS ───────────────────────────────────────────
        passed, msg, ema21 = await check_ema_trend(symbol, direction)
        result.filters.append(FilterResult("6", "EMA_TREND", passed, msg))
        if not passed:
            result.skip_reason = "EMA trend not aligned"
            return result

        # ── F7: RR Validation ────────────────────────────────────────────────
        if result.fvg_low and result.fvg_high:
            entry = current_price if current_price else (
                (result.fvg_low + result.fvg_high) / 2
            )
        elif result.fvg_optional_miss and choch_level:
            entry = current_price if current_price else choch_level
        elif current_price:
            entry = current_price
        else:
            entry = 0

        if entry == 0 or grab_level is None:
            result.filters.append(
                FilterResult("7", "RR", False, "RR: cannot compute ❌")
            )
            result.skip_reason = "RR calculation error"
            return result

        passed, msg, levels = check_rr_validator(direction, entry, grab_level)
        result.filters.append(FilterResult("7", "RR", passed, msg))
        if not passed:
            result.skip_reason = f"RR below {config.MIN_RR_RATIO}"
            return result

        # ── All filters passed ────────────────────────────────────────────────
        result.has_signal = True
        result.entry      = entry
        result.sl         = levels["sl"]
        result.tp1        = levels["tp1"]
        result.tp2        = levels["tp2"]
        result.rr         = levels["rr"]
        result.sl_pct     = levels["sl_pct"]

        # Fear & Greed value (needed for score — get from coingecko cache)
        try:
            from data.coingecko_client import coingecko
            fg_data = await coingecko.get_fear_greed()
            fg_val  = fg_data.get("value", 50)
        except Exception:
            fg_val = 50

        # Calculate base signal score (advanced bonuses added by engine.py
        # after OFI/CVD/Basis/Heatmap are fetched in parallel)
        result.signal_score, result.score_breakdown = _calculate_signal_score(
            result, fg_val, warn_results
        )

        confluence_tag = " [MULTI-TF]" if result.multitf_confluence else ""
        logger.info(
            f"✨ SIGNAL: {symbol} {direction}{confluence_tag} | "
            f"RR {levels['rr']:.1f} | Score {result.signal_score}/135 | "
            f"Entry {entry:.6g}"
        )
        return result


signal_engine = SignalEngine()
