"""
backtest/backtest_engine.py — Backtesting Engine for Arunabha Hybrid Bot v1.0
Replays historical OHLCV data. Signal-only P&L calculation.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

import config
from data.binance_client import binance

logger = logging.getLogger(__name__)
IST = pytz.timezone(config.TIMEZONE)


@dataclass
class BacktestTrade:
    symbol: str
    direction: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    rr: float
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    outcome: str = "OPEN"
    pnl_r: float = 0.0


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    period_days: int
    total_signals: int
    wins_tp1: int = 0
    wins_tp2: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_rr: float = 0.0
    total_r: float = 0.0
    trades: list[BacktestTrade] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"\n{'═'*44}\n"
            f"📊 BACKTEST: {self.symbol} | {self.timeframe} | {self.period_days}d\n"
            f"{'─'*44}\n"
            f"Total Signals : {self.total_signals}\n"
            f"Wins (TP1)    : {self.wins_tp1}\n"
            f"Wins (TP2)    : {self.wins_tp2}\n"
            f"Losses        : {self.losses}\n"
            f"Win Rate      : {self.win_rate:.1f}%\n"
            f"Avg RR        : {self.avg_rr:.2f}:1\n"
            f"Total R       : {self.total_r:.2f}R\n"
            f"{'═'*44}"
        )


class BacktestEngine:

    async def run(self, symbol: str, direction: str = "LONG", period_days: int = 30, timeframe: str = "15m") -> BacktestResult:
        logger.info(f"Starting backtest: {symbol} {direction} {period_days}d {timeframe}")

        candles_needed = 4 * 24 * period_days if timeframe == "15m" else 24 * period_days
        candles_needed = min(candles_needed, 1500)

        df = await binance.get_klines(symbol, timeframe, limit=candles_needed, use_cache=False)
        if df.empty or len(df) < 100:
            logger.warning(f"Insufficient data for backtest: {symbol}")
            return BacktestResult(symbol, timeframe, period_days, 0)

        result = BacktestResult(symbol=symbol, timeframe=timeframe, period_days=period_days, total_signals=0)
        trades: list[BacktestTrade] = []

        LOOKBACK = 50
        MIN_CANDLES_FORWARD = 20

        for i in range(LOOKBACK, len(df) - MIN_CANDLES_FORWARD):
            window = df.iloc[i - LOOKBACK:i]
            future = df.iloc[i:i + MIN_CANDLES_FORWARD]

            signal = self._check_signal_simplified(window, direction)
            if signal is None:
                continue

            entry, sl, grab_level = signal
            sl_distance = abs(entry - sl)
            if sl_distance == 0:
                continue

            tp1 = entry + sl_distance * 1.5 if direction == "LONG" else entry - sl_distance * 1.5
            tp2 = entry + sl_distance * 3.0 if direction == "LONG" else entry - sl_distance * 3.0

            trade = BacktestTrade(
                symbol=symbol, direction=direction,
                entry=entry, sl=sl, tp1=tp1, tp2=tp2, rr=3.0,
                entry_time=df.index[i],
            )

            for j, (idx, candle) in enumerate(future.iterrows()):
                if direction == "LONG":
                    if candle["low"] <= sl:
                        trade.outcome = "LOSS_SL"; trade.exit_price = sl; trade.exit_time = idx; trade.pnl_r = -1.0; break
                    elif candle["high"] >= tp2:
                        trade.outcome = "WIN_TP2"; trade.exit_price = tp2; trade.exit_time = idx; trade.pnl_r = 3.0; break
                    elif candle["high"] >= tp1:
                        trade.outcome = "WIN_TP1"; trade.exit_price = tp1; trade.exit_time = idx; trade.pnl_r = 1.5; break
                else:
                    if candle["high"] >= sl:
                        trade.outcome = "LOSS_SL"; trade.exit_price = sl; trade.exit_time = idx; trade.pnl_r = -1.0; break
                    elif candle["low"] <= tp2:
                        trade.outcome = "WIN_TP2"; trade.exit_price = tp2; trade.exit_time = idx; trade.pnl_r = 3.0; break
                    elif candle["low"] <= tp1:
                        trade.outcome = "WIN_TP1"; trade.exit_price = tp1; trade.exit_time = idx; trade.pnl_r = 1.5; break

            trades.append(trade)

        result.total_signals = len(trades)
        result.trades = trades
        result.wins_tp1 = sum(1 for t in trades if t.outcome == "WIN_TP1")
        result.wins_tp2 = sum(1 for t in trades if t.outcome == "WIN_TP2")
        result.losses = sum(1 for t in trades if t.outcome == "LOSS_SL")
        total_wins = result.wins_tp1 + result.wins_tp2
        result.win_rate = (total_wins / len(trades) * 100) if trades else 0
        result.total_r = sum(t.pnl_r for t in trades)
        result.avg_rr = (result.total_r / total_wins) if total_wins > 0 else 0

        print(result.summary())
        return result

    def _check_signal_simplified(self, df: pd.DataFrame, direction: str) -> Optional[tuple[float, float, float]]:
        if len(df) < 25:
            return None

        recent = df.iloc[-10:]
        current = df.iloc[-1]

        if direction == "LONG":
            lows = df["low"].values
            swing_low = np.min(lows[-25:-5])
            for candle_row in recent.itertuples():
                if candle_row.low < swing_low and candle_row.close > swing_low:
                    entry = float(current["close"])
                    sl = swing_low * (1 - config.SL_BUFFER_PCT)
                    if entry > sl:
                        return entry, sl, swing_low
        else:
            highs = df["high"].values
            swing_high = np.max(highs[-25:-5])
            for candle_row in recent.itertuples():
                if candle_row.high > swing_high and candle_row.close < swing_high:
                    entry = float(current["close"])
                    sl = swing_high * (1 + config.SL_BUFFER_PCT)
                    if sl > entry:
                        return entry, sl, swing_high

        return None


backtest_engine = BacktestEngine()
