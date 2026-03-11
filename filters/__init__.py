"""
filters/ — Arunabha Hybrid Bot v1.0 Signal Filter Chain

  F1  btc_regime.py       — BTC EMA9/21/200 + ADX. Blocks LONG in strong bear.
  F2  liquidity_grab.py   — Swing wick-hunt detection (15m).
  F3  choch.py            — Change of Character: structure break after grab.
  F4  fvg.py              — Fair Value Gap: 15m + 1h Multi-TF confluence. [UPGRADED]
  F4B pullback_quality.py — Fibonacci 30–62% retracement from pump peak. [NEW]
  F4C pump_age.py         — Pump must be < 2hr old (gainer/trending pairs). [NEW]
  F4D relative_volume.py  — 2-layer volume: 1h vs yesterday + 15m micro. [NEW]
  F5  volume_confirm.py   — CHoCH candle volume >= 2x avg.
  F6  ema_trend.py        — EMA21 on 1h alignment.
  F7  rr_validator.py     — Real RR >= MIN_RR_RATIO (2.5).

Notes:
  - F4B/F4C skip for core pairs (BTC/ETH/SOL/BNB/DOGE) automatically
  - F4D uses stricter thresholds for gainer pairs (2.0x vs 1.5x)
  - F4 Multi-TF: MULTITF_FVG_REQUIRED=False means 1h FVG warns but never hard-blocks
"""
