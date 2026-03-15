"""
core/ — Arunabha Hybrid Bot v1.0 — Core Package

┌─────────────────────────────────────────────────────────────────┐
│  File              │ কাজ                                        │
├─────────────────────────────────────────────────────────────────┤
│  engine.py         │ Main orchestrator — প্রতি ৫মিনিট scan,    │
│                    │ signal pass হলে সব module call করে,       │
│                    │ Telegram এ পাঠায়                          │
├─────────────────────────────────────────────────────────────────┤
│  signal_engine.py  │ 12-filter chain controller।               │
│                    │ Score 0-160 calculate করে                 │
│                    │ (base 0-100 + advanced bonus 0-60)        │
├─────────────────────────────────────────────────────────────────┤
│  scanner.py        │ কোন pair scan করবে decide করে।           │
│                    │ Core + Gainers + Trending + Anomaly       │
│                    │ সর্বোচ্চ 30টা pair                        │
├─────────────────────────────────────────────────────────────────┤
│  ai_rater.py       │ Signal A+/A/B/C rate করে।                │
│                    │ OpenAI → Ollama → Rule-based fallback     │
│                    │ Context-aware sentiment analysis           │
├─────────────────────────────────────────────────────────────────┤
│  ai_regime.py      │ Market phase detect করে।                  │
│                    │ Accumulation/Markup/Distribution/Markdown  │
│                    │ Multi-agent bull vs bear cross-check       │
├─────────────────────────────────────────────────────────────────┤
│  position_sizing.py│ ₹5,000 margin এ leverage + quantity       │
│                    │ হিসাব করে। Live USD/INR rate fetch করে   │
├─────────────────────────────────────────────────────────────────┤
│  scheduler.py      │ APScheduler — 5min scan, 1hr refresh,    │
│                    │ রাত 11:59 daily summary                   │
└─────────────────────────────────────────────────────────────────┘

Quick import:
  from core.engine        import engine
  from core.signal_engine import signal_engine
  from core.ai_regime     import get_regime, get_multiagent
  from core.ai_rater      import rate_signal
  from core.position_sizing import calculate_position
"""
