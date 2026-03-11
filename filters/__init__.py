"""
filters/ — Arunabha Hybrid Bot v1.0 Signal Filter Chain

  F1 btc_regime.py     — BTC EMA9/21/200 + ADX. Blocks LONG in strong bear.
  F2 liquidity_grab.py — Swing wick-hunt detection (15m).
  F3 choch.py          — Change of Character: structure break after grab.
  F4 fvg.py            — Fair Value Gap: 3-candle pattern.
  F5 volume_confirm.py — CHoCH candle volume >= 2x avg.
  F6 ema_trend.py      — EMA21 on 1h alignment.
  F7 rr_validator.py   — Real RR >= MIN_RR_RATIO (2.5).
"""
