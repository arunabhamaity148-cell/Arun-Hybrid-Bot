"""
filters/ — Arunabha Hybrid Bot v1.0 — Signal Filter Chain

12-step filter chain। Hard block = signal বাতিল। Warn only = score কমে।

┌──────┬───────────────────────┬────────────┬──────────────────────────────┐
│  ID  │ File                  │ Type       │ কাজ                          │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│  F0  │ news_sentiment.py     │ HARD BLOCK │ Context-aware news sentiment  │
│      │                       │            │ "SEC launches X" ≠ bullish   │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│  F1  │ btc_regime.py         │ HARD BLOCK │ BTC 4h EMA + ADX macro trend │
│  F1B │ btc_1h_bias.py        │ HARD BLOCK │ BTC 1h short-term momentum   │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│  F2  │ liquidity_grab.py     │ HARD BLOCK │ 15m swing wick hunt          │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│  F3  │ choch.py              │ HARD BLOCK │ 3-step CHoCH validation      │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│  F4  │ fvg.py                │ HARD BLOCK │ FVG — 15m + 1h confluence    │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│ F4B  │ pullback_quality.py   │ WARN ONLY  │ Fibonacci 30–62% zone        │
│ F4C  │ pump_age.py           │ WARN ONLY  │ Pump < 2hr freshness         │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│ F4D  │ relative_volume.py    │ HARD BLOCK │ 2-layer volume check         │
│ F4E  │ sell_pressure.py      │ HARD BLOCK │ Distribution detection       │
│ F4F  │ funding_rate.py       │ HARD BLOCK │ Crowd bias — ±0.10% block    │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│  F5  │ volume_confirm.py     │ WARN ONLY  │ CHoCH candle volume          │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│  F6  │ ema_trend.py          │ HARD BLOCK │ 1h EMA21 alignment           │
├──────┼───────────────────────┼────────────┼──────────────────────────────┤
│  F7  │ rr_validator.py       │ HARD BLOCK │ RR >= 2.5 (adaptive)         │
└──────┴───────────────────────┴────────────┴──────────────────────────────┘

Advanced filters (score boosters — never block):
┌────────────────────────┬──────────────────────────────────────────────┐
│ dynamic_params.py      │ ATR-based SL/TP + adaptive RR threshold      │
│ liquidity_heatmap.py   │ Order book walls → TP snap + TOD caution     │
│ volume_spike_guard.py  │ Removed from chain (contradicts F4D)         │
└────────────────────────┴──────────────────────────────────────────────┘

Notes:
  F4B/F4C/sell_pressure skip core pairs (BTC/ETH/SOL/BNB/DOGE) automatically
  F4D uses stricter threshold for gainer pairs (2.0x vs 1.5x)
  MULTITF_FVG_REQUIRED=False → 1h FVG warns but never hard-blocks
  dynamic_params reads config.LEVERAGE_MIN/MAX, not hardcoded

Quick import:
  from filters.btc_regime        import check_btc_regime
  from filters.dynamic_params    import get_dynamic_params
  from filters.liquidity_heatmap import get_heatmap_result
"""
