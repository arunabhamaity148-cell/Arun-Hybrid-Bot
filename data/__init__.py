"""
data/ — Arunabha Hybrid Bot v1.0 — Data Package

┌─────────────────────────────────────────────────────────────────┐
│  File                  │ কাজ                                    │
├─────────────────────────────────────────────────────────────────┤
│  binance_client.py     │ Binance Futures REST + WebSocket।     │
│                        │ OHLCV, price, funding rate, volume    │
│                        │ anomaly detection। NEVER places order │
├─────────────────────────────────────────────────────────────────┤
│  delta_client.py       │ Delta Exchange — candle (get_klines), │
│                        │ mark price। Read-only, no trading     │
├─────────────────────────────────────────────────────────────────┤
│  coingecko_client.py   │ Fear & Greed, trending coins,         │
│                        │ market caps। Free tier                │
├─────────────────────────────────────────────────────────────────┤
│  market_intel.py       │ 3-source intel: CoinGecko sentiment,  │
│                        │ CoinDesk RSS headlines, CMC volume    │
├─────────────────────────────────────────────────────────────────┤
│  ofi_cvd.py            │ Order Flow Imbalance + CVD।           │
│                        │ aggTrades থেকে buyer/seller ratio।   │
│                        │ Funding divergence detect করে        │
├─────────────────────────────────────────────────────────────────┤
│  cross_basis.py        │ Futures vs Spot price gap।            │
│                        │ Overheated/backwardation detect করে  │
├─────────────────────────────────────────────────────────────────┤
│  pattern_recognition.py│ Candle patterns — Hammer, Engulfing,  │
│                        │ Morning Star, 3 Soldiers ইত্যাদি।    │
│                        │ Rule-based + optional Ollama AI       │
├─────────────────────────────────────────────────────────────────┤
│  cache_manager.py      │ Async in-memory TTL cache।            │
│                        │ API calls কমায়, rate limit বাঁচায়   │
├─────────────────────────────────────────────────────────────────┤
│  coindcx_client.py     │ Placeholder (unused)                  │
└─────────────────────────────────────────────────────────────────┘

Quick import:
  from data.binance_client      import binance
  from data.delta_client        import delta
  from data.coingecko_client    import coingecko
  from data.market_intel        import get_intel
  from data.ofi_cvd             import get_ofi_cvd
  from data.cross_basis         import get_cross_basis
  from data.pattern_recognition import get_patterns
  from data.cache_manager       import cache
"""
