"""
notification/ — Arunabha Hybrid Bot v1.0 — Notification Package

┌──────────────────────┬────────────────────────────────────────────┐
│ File                 │ কাজ                                        │
├──────────────────────┼────────────────────────────────────────────┤
│ telegram_bot.py      │ Outbound signals + inbound commands        │
│                      │ Signal format: score/160 + all sections    │
└──────────────────────┴────────────────────────────────────────────┘

Available Commands:
  Scan Control:  /scan /add /remove /news /block
  Stats:         /status /signals /score /regime /perf
  Analysis:      /pattern /ofi /backtest
  Trade Track:   /sl /tp1 /win /reset
  Info:          /start /help

Signal message sections (in order):
  1. Pair + Setup + Direction
  2. Levels (Grab / CHoCH / FVG / Entry / SL / TP1 / TP2 / RR)
  3. Signal Score (0-160) + breakdown bar
  4. Why This Coin (volume spike / trending rank)
  5. Position Sizing (₹5K margin, leverage, quantity, loss/profit)
  6. Order Flow (OFI + CVD + Basis)
  7. Regime Detection + Candle Patterns
  8. Multi-Agent Analysis (bull vs bear)
  9. ATR SL adjustment note (if changed)
  10. Market Intelligence (CoinGecko + CoinDesk + CMC)
  11. Market Context (BTC / F&G / Funding / Session)
  12. AI Rating (A+/A/B/C + reason)

Quick import:
  from notification.telegram_bot import telegram_bot
  await telegram_bot.send_message(text)
"""
