"""
backtest/ — Arunabha Hybrid Bot v1.0 Backtesting Package
  backtest_engine.py — Walk-forward backtester on historical OHLCV.

Usage:
  from backtest.backtest_engine import backtest_engine
  result = await backtest_engine.run("BTCUSDT", direction="LONG", period_days=30)
  print(result.summary())
"""
