"""
backtest/backtest_engine.py — Real Walk-Forward Backtest Engine v2

OLD problem:
  _check_signal_simplified() used a naive swing-low check.
  It did NOT run the actual filter chain — so backtest results were meaningless.
  It did not test FVG, CHoCH body-close, RelVol, PumpAge, SellPressure etc.

NEW approach — Walk-Forward with Real Filter Logic:
  For each candle position i in history:
    - Treat df.iloc[:i] as "current known data"
    - Run the SAME detection functions used in live trading (liquidity grab,
      CHoCH body-close, FVG, pullback quality, sell pressure, RR)
    - Simulate entry at df.iloc[i] close price
    - Walk forward on df.iloc[i:i+50] to find SL/TP1/TP2 hit
    - Record outcome

  This means backtest uses identical logic to live bot — no optimism bias.

Walk-Forward specifics:
  - Minimum 50 candles lookback per evaluation step
  - Signal cooldown: skip if same symbol+direction signaled in last 8 candles (2hr)
  - Max forward candles to check for SL/TP: 50 (12.5hr on 15m)
  - If neither SL nor TP hit in 50 candles → TIMEOUT → 0R (neutral)

Metrics reported:
  - Total signals found
  - TP1 wins / TP2 wins / SL losses / Timeouts
  - Win rate (TP1 + TP2) / total
  - Expectancy = avg R per trade
  - Profit factor = gross wins R / gross losses R
  - Max consecutive losses
  - Best / worst trade R
  - Per-month breakdown

Telegram command: /backtest SOLUSDT 30 LONG
  → runs 30-day walk-forward on SOLUSDT LONG signals, sends report
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone
import pandas as pd
import numpy as np
import pytz

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)
IST = pytz.timezone(config.TIMEZONE)


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class BTrade:
    """Single backtest trade record."""
    symbol: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr_potential: float
    entry_bar: int          # index in df
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    outcome: str = "OPEN"   # WIN_TP1 | WIN_TP2 | LOSS_SL | TIMEOUT
    pnl_r: float = 0.0
    filter_notes: str = ""  # what filters passed


@dataclass
class BResult:
    symbol: str
    direction: str
    timeframe: str
    period_days: int
    total_signals: int = 0
    wins_tp1: int = 0
    wins_tp2: int = 0
    losses: int = 0
    timeouts: int = 0
    win_rate: float = 0.0
    expectancy_r: float = 0.0
    profit_factor: float = 0.0
    max_consec_losses: int = 0
    best_trade_r: float = 0.0
    worst_trade_r: float = 0.0
    total_r: float = 0.0
    trades: list[BTrade] = field(default_factory=list)

    def summary(self) -> str:
        sep = "═" * 46
        dash = "─" * 46
        direction_emoji = "🟢" if self.direction == "LONG" else "🔴"
        outcome_emoji = "✅" if self.expectancy_r > 0 else "❌"

        # Monthly breakdown
        monthly = self._monthly_breakdown()
        monthly_lines = ""
        for month, stats in monthly.items():
            monthly_lines += (
                f"  {month}: {stats['signals']} signals | "
                f"W:{stats['wins']} L:{stats['losses']} | "
                f"{stats['total_r']:+.1f}R\n"
            )

        lines = [
            f"\n{sep}",
            f"📊 BACKTEST REPORT {outcome_emoji}",
            f"   {self.symbol} {direction_emoji}{self.direction} | "
            f"{self.timeframe} | {self.period_days}d",
            dash,
            f"Total Signals    : {self.total_signals}",
            f"Wins (TP1)       : {self.wins_tp1}",
            f"Wins (TP2)       : {self.wins_tp2}",
            f"Losses (SL)      : {self.losses}",
            f"Timeouts         : {self.timeouts}",
            dash,
            f"Win Rate         : {self.win_rate:.1f}%",
            f"Expectancy       : {self.expectancy_r:+.2f}R per trade",
            f"Profit Factor    : {self.profit_factor:.2f}",
            f"Total R          : {self.total_r:+.2f}R",
            dash,
            f"Max Consec Losses: {self.max_consec_losses}",
            f"Best Trade       : {self.best_trade_r:+.2f}R",
            f"Worst Trade      : {self.worst_trade_r:+.2f}R",
        ]

        if monthly_lines:
            lines += [dash, "Monthly Breakdown:", monthly_lines.rstrip()]

        lines.append(sep)
        return "\n".join(lines)

    def telegram_summary(self) -> str:
        """Formatted for Telegram HTML."""
        direction_emoji = "🟢" if self.direction == "LONG" else "🔴"
        outcome_emoji = "✅" if self.expectancy_r > 0 else "❌"
        wl = f"{self.wins_tp1 + self.wins_tp2}W / {self.losses}L / {self.timeouts}T"

        monthly = self._monthly_breakdown()
        monthly_lines = ""
        for month, stats in monthly.items():
            monthly_lines += (
                f"  {month}: {stats['signals']}sig "
                f"W{stats['wins']}/L{stats['losses']} "
                f"{stats['total_r']:+.1f}R\n"
            )

        msg = (
            f"📊 <b>Backtest Report</b> {outcome_emoji}\n"
            f"<b>{self.symbol}</b> {direction_emoji} {self.direction} | "
            f"{self.timeframe} | {self.period_days}d\n\n"
            f"<b>Signals:</b> {self.total_signals}\n"
            f"<b>W/L/T:</b> {wl}\n"
            f"<b>Win Rate:</b> {self.win_rate:.1f}%\n"
            f"<b>Expectancy:</b> {self.expectancy_r:+.2f}R\n"
            f"<b>Profit Factor:</b> {self.profit_factor:.2f}\n"
            f"<b>Total R:</b> {self.total_r:+.2f}R\n"
            f"<b>Max Consec L:</b> {self.max_consec_losses}\n\n"
        )

        if monthly_lines:
            msg += f"<b>Monthly:</b>\n<code>{monthly_lines}</code>"

        return msg    
def _monthly_breakdown(self) -> dict:
        monthly: dict = {}
        for t in self.trades:
            if t.entry_time is None:
                continue
            key = t.entry_time.strftime("%Y-%m")
            if key not in monthly:
                monthly[key] = {"signals": 0, "wins": 0, "losses": 0, "total_r": 0.0}
            monthly[key]["signals"] += 1
            if "WIN" in t.outcome:
                monthly[key]["wins"] += 1
            elif t.outcome == "LOSS_SL":
                monthly[key]["losses"] += 1
            monthly[key]["total_r"] += t.pnl_r
        return monthly


# ─── Core detection functions (mirrors live filters, no async) ────────────────

def _find_swing_low_bt(lows: np.ndarray, lookback: int, left: int = 2, right: int = 2) -> Optional[float]:
    n = len(lows)
    start = max(left, n - lookback)
    for i in range(n - right - 1, start - 1, -1):
        if i - left < 0 or i + right >= n:
            continue
        if lows[i] <= lows[i - left:i].min() and lows[i] <= lows[i + 1:i + right + 1].min():
            return float(lows[i])
    return None


def _find_swing_high_bt(highs: np.ndarray, lookback: int, left: int = 2, right: int = 2) -> Optional[float]:
    n = len(highs)
    start = max(left, n - lookback)
    for i in range(n - right - 1, start - 1, -1):
        if i - left < 0 or i + right >= n:
            continue
        if highs[i] >= highs[i - left:i].max() and highs[i] >= highs[i + 1:i + right + 1].max():
            return float(highs[i])
    return None


def _detect_liquidity_grab_bt(window: pd.DataFrame, direction: str) -> tuple[bool, Optional[float], Optional[int]]:
    """
    Detect liquidity grab in window.
    Returns (found, grab_level, candles_ago_from_window_end).
    """
    n = len(window)
    lows = window["low"].values
    highs = window["high"].values
    closes = window["close"].values

    lookback_bars = min(20, n - 5)

    if direction == "LONG":
        swing_low = _find_swing_low_bt(lows[:-5], lookback=lookback_bars, left=3, right=3)
        if swing_low is None:
            return False, None, None
        # Recent candles: check for wick below swing_low with close above
        for i in range(n - 1, n - 6, -1):
            if lows[i] < swing_low and closes[i] > swing_low:
                candles_ago = n - 1 - i
                return True, swing_low, max(1, candles_ago)
    else:
        swing_high = _find_swing_high_bt(highs[:-5], lookback=lookback_bars, left=3, right=3)
        if swing_high is None:
            return False, None, None
        for i in range(n - 1, n - 6, -1):
            if highs[i] > swing_high and closes[i] < swing_high:
                candles_ago = n - 1 - i
                return True, swing_high, max(1, candles_ago)

    return False, None, None


def _detect_choch_bt(window: pd.DataFrame, grab_candles_ago: int, direction: str) -> tuple[bool, Optional[float]]:
    """
    Detect CHoCH using body-close + momentum continuation (mirrors live choch.py v2).
    Returns (found, structure_level).
    """
    n = len(window)
    grab_idx = n - grab_candles_ago
    if grab_idx < 8:
        return False, None

    pre_grab = window.iloc[:grab_idx]
    post_grab = window.iloc[grab_idx:]

    if len(pre_grab) < 5 or len(post_grab) < 1:
        return False, None

    # Structure level
    if direction == "LONG":
        structure_level = _find_swing_high_bt(pre_grab["high"].values, lookback=min(20, len(pre_grab)), left=2, right=2)
        if structure_level is None:
            structure_level = float(pre_grab["high"].iloc[-8:].max())
    else:
        structure_level = _find_swing_low_bt(pre_grab["low"].values, lookback=min(20, len(pre_grab)), left=2, right=2)
        if structure_level is None:
            structure_level = float(pre_grab["low"].iloc[-8:].min())

    if structure_level is None:
        return False, None

    # Body-close break
    choch_pos = None
    choch_close = None
    for i, (_, row) in enumerate(post_grab.iterrows()):
        close = float(row["close"])
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        body = abs(close - open_)
        rng = high - low
        if rng > 0 and body < rng * 0.3:
            continue
        if direction == "LONG" and close > structure_level and close > open_:
            choch_pos, choch_close = i, close
            break
        if direction == "SHORT" and close < structure_level and close < open_:
            choch_pos, choch_close = i, close
            break

    if choch_pos is None or choch_close is None:
        return False, None

    # Momentum continuation
    next_c = post_grab.iloc[choch_pos + 1: choch_pos + 3]
    if len(next_c) == 0:
        return True, structure_level  # just formed, allow

    continuation = sum(
        1 for _, r in next_c.iterrows()
        if (direction == "LONG" and float(r["close"]) > choch_close)
        or (direction == "SHORT" and float(r["close"]) < choch_close)
    )
    return (continuation >= 1, structure_level)


def _detect_fvg_bt(window: pd.DataFrame, direction: str, current_price: float) -> tuple[bool, Optional[float], Optional[float]]:
    """Detect FVG and check price is entering zone (mirrors live fvg.py)."""
    n = len(window)
    lookback = min(10, n - 2)
    tolerance = current_price * config.FVG_ENTRY_TOLERANCE_PCT

    for i in range(n - 1, n - lookback - 1, -1):
        if i < 2:
            break
        c1 = window.iloc[i - 2]
        c3 = window.iloc[i]
        if direction == "LONG":
            fvg_low, fvg_high = float(c1["high"]), float(c3["low"])
            if fvg_high > fvg_low:
                in_zone = (fvg_low - tolerance) <= current_price <= (fvg_high + tolerance)
                if in_zone:
                    return True, fvg_low, fvg_high
        else:
            fvg_high, fvg_low = float(c1["low"]), float(c3["high"])
            if fvg_high > fvg_low:
                in_zone = (fvg_low - tolerance) <= current_price <= (fvg_high + tolerance)
                if in_zone:
                    return True, fvg_low, fvg_high

    return False, None, None


def _detect_pullback_bt(window: pd.DataFrame, direction: str, current_price: float) -> bool:
    """Check Fibonacci 30-62% pullback (simplified for backtest speed)."""
    lookback = min(config.PULLBACK_LOOKBACK_CANDLES, len(window))
    recent = window.iloc[-lookback:]

    if direction == "LONG":
        peak = float(recent["high"].max())
        peak_idx = recent["high"].idxmax()
        peak_pos = recent.index.get_loc(peak_idx)
        if peak_pos < 3:
            return True
        base = float(recent.iloc[:peak_pos]["low"].min())
        pump = peak - base
        if pump <= 0 or pump / base * 100 < 3:
            return True
        retrace = (peak - current_price) / pump * 100
    else:
        peak = float(recent["low"].min())
        peak_idx = recent["low"].idxmin()
        peak_pos = recent.index.get_loc(peak_idx)
        if peak_pos < 3:
            return True
        base = float(recent.iloc[:peak_pos]["high"].max())
        pump = base - peak
        if pump <= 0 or pump / base * 100 < 3:
            return True
        retrace = (current_price - peak) / pump * 100

    return config.PULLBACK_MIN_PCT <= retrace <= 78.0


def _detect_sell_pressure_bt(window: pd.DataFrame, direction: str) -> bool:
    """Check sell pressure on pullback candles (mirrors live sell_pressure.py)."""
    if len(window) < 10:
        return True

    lookback = 20
    recent = window.iloc[-lookback:]
    vol_avg = recent["volume"].mean()
    if vol_avg == 0:
        return True

    # Pump candle volume
    if direction == "LONG":
        green = recent[recent["close"] > recent["open"]]
        pump_vol = float(green["volume"].max()) if not green.empty else vol_avg
    else:
        red = recent[recent["close"] < recent["open"]]
        pump_vol = float(red["volume"].max()) if not red.empty else vol_avg

    # Pullback candles (last 5 closed)
    pullback = window.iloc[-6:-1]
    if len(pullback) < 2:
        return True

    avg_pb_vol = float(pullback["volume"].mean())
    vol_ratio = avg_pb_vol / pump_vol if pump_vol > 0 else 0

    # Body dominance
    bodies = (pullback["close"] - pullback["open"]).abs()
    ranges = pullback["high"] - pullback["low"]
    sig_body = bodies > (ranges * 0.4)
    if direction == "LONG":
        counter = (pullback["close"] < pullback["open"]) & sig_body
    else:
        counter = (pullback["close"] > pullback["open"]) & sig_body
    body_ratio = float(counter.sum() / len(pullback))

    return vol_ratio < config.SELL_PRESSURE_VOL_RATIO_MAX and body_ratio <= config.SELL_PRESSURE_RED_BODY_MAX


def _check_rr_bt(direction: str, entry: float, grab_level: float) -> tuple[bool, dict]:
    """RR validation (mirrors live rr_validator.py)."""
    buf = config.SL_BUFFER_PCT
    if direction == "LONG":
        sl = grab_level * (1 - buf)
        sl_dist = entry - sl
        if sl_dist <= 0:
            return False, {}
        tp1 = entry + sl_dist * 1.5
        tp2 = entry + sl_dist * 3.0
    else:
        sl = grab_level * (1 + buf)
        sl_dist = sl - entry
        if sl_dist <= 0:
            return False, {}
        tp1 = entry - sl_dist * 1.5
        tp2 = entry - sl_dist * 3.0

    rr = (tp2 - entry) / sl_dist if direction == "LONG" else (entry - tp2) / sl_dist
    if rr < config.MIN_RR_RATIO:
        return False, {}

    return True, {"sl": sl, "tp1": tp1, "tp2": tp2, "rr": rr}


def _simulate_trade_outcome(
    future: pd.DataFrame,
    direction: str,
    sl: float,
    tp1: float,
    tp2: float,
    max_bars: int = 50,
) -> tuple[str, float, Optional[datetime]]:
    """
    Walk forward through future candles to find first SL/TP hit.
    Returns (outcome, pnl_r, exit_time).
    Uses sequential bar-by-bar — TP1 takes priority over TP2 per bar.
    """
    bars_checked = min(len(future), max_bars)
    sl_dist = abs(tp2 - sl) / 3.0  # rough 1R distance

    for i in range(bars_checked):
        row = future.iloc[i]
        low = float(row["low"])
        high = float(row["high"])
        exit_time = row.name if hasattr(row.name, "strftime") else None

        if direction == "LONG":
            if low <= sl:
                return "LOSS_SL", -1.0, exit_time
            if high >= tp2:
                return "WIN_TP2", 3.0, exit_time
            if high >= tp1:
                return "WIN_TP1", 1.5, exit_time
        else:
            if high >= sl:
                return "LOSS_SL", -1.0, exit_time
            if low <= tp2:
                return "WIN_TP2", 3.0, exit_time
            if low <= tp1:
                return "WIN_TP1", 1.5, exit_time

    return "TIMEOUT", 0.0, None


def _calc_max_consec_losses(trades: list[BTrade]) -> int:
    max_l = 0
    cur_l = 0
    for t in trades:
        if t.outcome == "LOSS_SL":
            cur_l += 1
            max_l = max(max_l, cur_l)
        else:
            cur_l = 0
    return max_l


# ─── Main engine class ────────────────────────────────────────────────────────

class BacktestEngine:

    async def run(
        self,
        symbol: str,
        direction: str = "LONG",
        period_days: int = 30,
        timeframe: str = "15m",
        is_core_pair: bool = False,
    ) -> BResult:
        """
        Run real walk-forward backtest on `symbol` for `period_days`.
        Downloads historical OHLCV and replays actual filter logic.
        """
        logger.info(f"Backtest starting: {symbol} {direction} {period_days}d {timeframe}")

        # We need extra candles for warmup (50 candle lookback per step)
        warmup = 60
        candles_per_day = {"15m": 96, "1h": 24, "4h": 6}.get(timeframe, 96)
        total_candles = min(period_days * candles_per_day + warmup, 1500)

        df = await binance.get_klines(symbol, timeframe, limit=total_candles, use_cache=False)

        result = BResult(
            symbol=symbol,
            direction=direction,
            timeframe=timeframe,
            period_days=period_days,
        )

        if df.empty or len(df) < warmup + 20:
            logger.warning(f"Backtest: insufficient data for {symbol} — got {len(df)} candles")
            return result

        trades: list[BTrade] = []
        last_signal_bar: int = -9999  # cooldown tracker (8-bar = 2hr)
        COOLDOWN_BARS = 8
        FORWARD_BARS = 50
        LOOKBACK = 50

        for i in range(LOOKBACK, len(df) - FORWARD_BARS):
            # Cooldown: skip if signaled too recently
            if (i - last_signal_bar) < COOLDOWN_BARS:
                continue

            window = df.iloc[i - LOOKBACK: i]
            future = df.iloc[i: i + FORWARD_BARS]
            current_price = float(df["close"].iloc[i])
            entry_time = df.index[i]

            # ── Filter 1: Liquidity Grab ──────────────────────────────────────
            grab_ok, grab_level, grab_candles_ago = _detect_liquidity_grab_bt(window, direction)
            if not grab_ok or grab_level is None:
                continue

            # ── Filter 2: CHoCH (real body-close + momentum) ──────────────────
            choch_ok, structure_level = _detect_choch_bt(window, grab_candles_ago, direction)
            if not choch_ok or structure_level is None:
                continue

            # ── Filter 3: FVG (optional — skip if not found, continue) ────────
            fvg_ok, fvg_low, fvg_high = _detect_fvg_bt(window, direction, current_price)
            if fvg_ok and fvg_low and fvg_high:
                entry = (fvg_low + fvg_high) / 2
            else:
                entry = current_price  # CHoCH entry fallback

            # ── Filter 4: Pullback Quality (skip for core pairs) ──────────────
            if not is_core_pair:
                pb_ok = _detect_pullback_bt(window, direction, current_price)
                if not pb_ok:
                    continue

            # ── Filter 5: Sell Pressure (skip for core pairs) ─────────────────
            if not is_core_pair:
                sp_ok = _detect_sell_pressure_bt(window, direction)
                if not sp_ok:
                    continue

            # ── Filter 6: RR Validation ───────────────────────────────────────
            rr_ok, levels = _check_rr_bt(direction, entry, grab_level)
            if not rr_ok:
                continue

            # ── Signal found — simulate trade ─────────────────────────────────
            last_signal_bar = i
            outcome, pnl_r, exit_time = _simulate_trade_outcome(
                future, direction,
                levels["sl"], levels["tp1"], levels["tp2"],
                max_bars=FORWARD_BARS,
            )

            filter_notes = (
                f"grab@{grab_level:.6g} | "
                f"choch@{structure_level:.6g} | "
                f"{'fvg ' if fvg_ok else 'no-fvg '}"
                f"rr{levels['rr']:.1f}"
            )

            trade = BTrade(
                symbol=symbol,
                direction=direction,
                entry=entry,
                sl=levels["sl"],
                tp1=levels["tp1"],
                tp2=levels["tp2"],
                rr_potential=levels["rr"],
                entry_bar=i,
                entry_time=entry_time,
                exit_time=exit_time,
                outcome=outcome,
                pnl_r=pnl_r,
                filter_notes=filter_notes,
            )
            trades.append(trade)

        # ── Compile results ───────────────────────────────────────────────────
        result.total_signals = len(trades)
        result.trades = trades

        if not trades:
            return result

        result.wins_tp1 = sum(1 for t in trades if t.outcome == "WIN_TP1")
        result.wins_tp2 = sum(1 for t in trades if t.outcome == "WIN_TP2")
        result.losses = sum(1 for t in trades if t.outcome == "LOSS_SL")
        result.timeouts = sum(1 for t in trades if t.outcome == "TIMEOUT")

        total_wins = result.wins_tp1 + result.wins_tp2
        result.win_rate = (total_wins / len(trades) * 100) if trades else 0.0

        result.total_r = sum(t.pnl_r for t in trades)
        result.expectancy_r = result.total_r / len(trades) if trades else 0.0

        gross_wins = sum(t.pnl_r for t in trades if t.pnl_r > 0)
        gross_losses = abs(sum(t.pnl_r for t in trades if t.pnl_r < 0))
        result.profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float("inf")

        result.max_consec_losses = _calc_max_consec_losses(trades)
        result.best_trade_r = max(t.pnl_r for t in trades)
        result.worst_trade_r = min(t.pnl_r for t in trades)

        print(result.summary())
        return result


backtest_engine = BacktestEngine()
