# 🤖 Arunabha Hybrid Bot v1.0

**Advanced Signal-Only Crypto Trading Bot | Delta Exchange | Telegram Alerts**

> ⚠️ **Signal-only mode — কোনো auto trade নেই। সব manually Delta Exchange এ execute করো।**

---

## 📋 সংক্ষিপ্ত পরিচয়

Arunabha Hybrid Bot প্রতি ৫ মিনিটে সর্বোচ্চ ৩০টা crypto pair স্ক্যান করে, ১২টা filter chain এর মধ্য দিয়ে পাঠায়, এবং শুধুমাত্র high-quality signal Telegram এ পাঠায়।

**Signal Score: 0–160** (Base 0–100 + Advanced Bonus 0–60)

---

## 🗂️ ফাইল স্ট্রাকচার

```
Arun-Hybrid-Bot-main/
│
├── main.py                    ← Entry point (FastAPI + bot start)
├── config.py                  ← সব settings (API keys, thresholds)
├── requirements.txt           ← Python dependencies
├── .env                       ← Secret keys (NEVER GitHub এ push করবে না)
├── start_bot.ps1              ← Windows double-click launcher
├── start_bot.bat              ← Backup launcher
├── setup_first_time.ps1       ← First time setup script
│
├── core/
│   ├── engine.py              ← Main orchestrator
│   ├── signal_engine.py       ← 12-filter chain + score 0-160
│   ├── scanner.py             ← Pair selection (30 pairs max)
│   ├── ai_rater.py            ← Signal rating A+/A/B/C
│   ├── ai_regime.py           ← Regime detection + multi-agent
│   ├── position_sizing.py     ← ₹5,000 margin sizing
│   └── scheduler.py           ← 5min scan, daily summary
│
├── data/
│   ├── binance_client.py      ← Binance Futures data (read-only)
│   ├── delta_client.py        ← Delta Exchange data (read-only)
│   ├── coingecko_client.py    ← Fear & Greed, trending
│   ├── market_intel.py        ← 3-source intel (CG + CoinDesk + CMC)
│   ├── ofi_cvd.py             ← Order Flow Imbalance + CVD
│   ├── cross_basis.py         ← Futures vs Spot basis
│   ├── pattern_recognition.py ← Candle pattern detection
│   └── cache_manager.py       ← In-memory TTL cache
│
├── filters/
│   ├── news_sentiment.py      ← F0: Context-aware news (HARD BLOCK)
│   ├── btc_regime.py          ← F1: BTC 4h macro (HARD BLOCK)
│   ├── btc_1h_bias.py         ← F1B: BTC 1h bias (HARD BLOCK)
│   ├── liquidity_grab.py      ← F2: Swing wick hunt (HARD BLOCK)
│   ├── choch.py               ← F3: CHoCH 3-step (HARD BLOCK)
│   ├── fvg.py                 ← F4: FVG 15m+1h (HARD BLOCK)
│   ├── pullback_quality.py    ← F4B: Fibonacci zone (WARN ONLY)
│   ├── pump_age.py            ← F4C: Pump freshness (WARN ONLY)
│   ├── relative_volume.py     ← F4D: 2-layer volume (HARD BLOCK)
│   ├── sell_pressure.py       ← F4E: Distribution (HARD BLOCK)
│   ├── funding_rate.py        ← F4F: Crowd bias (HARD BLOCK)
│   ├── volume_confirm.py      ← F5: CHoCH volume (WARN ONLY)
│   ├── ema_trend.py           ← F6: EMA21 1h (HARD BLOCK)
│   ├── rr_validator.py        ← F7: RR >= 2.5 (HARD BLOCK)
│   ├── dynamic_params.py      ← ATR SL/TP + adaptive threshold
│   ├── liquidity_heatmap.py   ← TP snap + TOD caution
│   └── volume_spike_guard.py  ← Removed from chain (file exists)
│
├── notification/
│   └── telegram_bot.py        ← Signal sender + all commands
│
└── backtest/
    └── backtest_engine.py     ← Walk-forward backtester
```

---

## 🚀 Setup — প্রথমবার

### Step 1: Python Install
[python.org](https://www.python.org/downloads/) থেকে Python 3.11+ install করো।
⚠️ Install এর সময় **"Add Python to PATH"** অবশ্যই tick করো।

### Step 2: First Time Setup
```
setup_first_time.ps1 → right click → Run with PowerShell
```
এটা automatically করবে:
- Python check
- `.env` file তৈরি + API keys দেওয়ার সুযোগ
- Virtual environment তৈরি
- সব packages install
- PowerShell permission fix

### Step 3: .env ফাইল
`.env` file এ এই keys দাও:
```env
BINANCE_API_KEY=
BINANCE_SECRET=

DELTA_API_KEY=
DELTA_SECRET=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

OPENAI_API_KEY=          # Optional — $4 দিয়ে ~20,000 signals

# Optional:
CRYPTOPANIC_TOKEN=
CMC_API_KEY=
COINGECKO_API_KEY=
```

### Step 4: প্রতিদিন চালাতে
```
start_bot.ps1 → right click → Run with PowerShell
```

---

## 📡 Signal কীভাবে Generate হয়

```
প্রতি ৫ মিনিট
    ↓
৩০টা pair scan
    ↓
Fear & Greed direction check
    ↓
12-filter chain (LONG + SHORT উভয়)
    ↓
Signal pass হলে:
    ├── OFI + CVD + Cross-Basis fetch (parallel)
    ├── Pattern Recognition
    ├── Regime Detection (AI)
    ├── ATR Dynamic SL/TP adjust
    ├── Multi-Agent cross-check (AI)
    ├── Market Intel (CG + CoinDesk + CMC)
    ├── Position Sizing (₹5K margin)
    └── AI Rating (OpenAI → Ollama → Rule-based)
          ↓
    Telegram Signal Message
```

---

## 🎯 Signal Score — 0 to 160

### Base Score (0-100)
| Component | Max |
|-----------|-----|
| RR Quality | 30 |
| Multi-TF FVG | 20 |
| Funding Rate | 15 |
| Fear & Greed | 15 |
| Session (NY/London) | 10 |
| Warn Filters | 10 |

### Advanced Bonus (0-60)
| Component | Range |
|-----------|-------|
| OFI + CVD + Flow | 0 to +25 |
| Regime Detection | -5 to +10 |
| Multi-Agent | -8 to +8 |
| Pattern Recognition | -5 to +8 |
| Cross-Exchange Basis | 0 to +5 |
| Liq Heatmap + TOD | 0 to +5 |

### Score Labels
| Score | Label | Leverage |
|-------|-------|----------|
| 130+ | 💎 Elite Setup | 20x |
| 110+ | 🔥🔥 High Conviction | 20x |
| 85+ | 🔥 Good Setup | 17x |
| 65+ | ✅ Moderate | 15x |
| 50+ | ⚠️ Caution | — |
| <50 | ❗ Weak | skip |

---

## 📱 Telegram Commands

### Scan Control
| Command | কাজ |
|---------|-----|
| `/scan` | Manual scan trigger |
| `/add PEPE` | Pair add করো |
| `/remove PEPE` | Pair remove করো |
| `/news DOGE` | News-driven flag |
| `/block SHIB` | Signal block |

### Stats & Info
| Command | কাজ |
|---------|-----|
| `/status` | Bot status, BTC regime, F&G |
| `/signals` | আজকের signals |
| `/score` | Score system explain |
| `/regime` | Market regime detect |
| `/perf` | Win/loss summary |

### Analysis
| Command | কাজ |
|---------|-----|
| `/pattern SOLUSDT` | Candle patterns |
| `/ofi SOLUSDT` | Order flow analysis |
| `/backtest SOLUSDT 30` | 30-day backtest |

### Trade Tracking
| Command | কাজ |
|---------|-----|
| `/sl` | SL hit report |
| `/tp1` | TP1 partial exit |
| `/win` | Full win report |
| `/reset` | Daily counters reset |

---

## 💰 Position Sizing

প্রতি trade এ fixed **₹5,000 margin**। Signal score দেখে leverage:

```
Score 80+  → 20x → ₹1,00,000 position
Score 65+  → 17x → ₹85,000 position
Score 50+  → 15x → ₹75,000 position
Score <50  → Skip suggestion
```

Live USD/INR rate fetch হয় (fallback: ₹83.5)।

---

## 🧠 AI Features

### 1. Regime Detection
Market phase classify করে (Wyckoff):
- **ACCUMULATION** → LONG bias
- **MARKUP** → LONG momentum
- **DISTRIBUTION** → SHORT bias
- **MARKDOWN** → SHORT only

OpenAI → Ollama → Rule-based fallback।

### 2. Multi-Agent Cross-Check
দুটো AI agent আলাদাভাবে দেখে:
- 🟢 Bull Agent: "কেন নেবো"
- 🔴 Bear Agent: "কী ভুল হতে পারে"

Verdict: PROCEED / CAUTION / SKIP

### 3. ATR Dynamic SL/TP
Market volatility দেখে SL adjust:
- HIGH volatility → SL wider (false stop-out কমায়)
- LOW volatility → SL tighter (capital protect)

### 4. Pattern Recognition
Classic candle patterns detect করে:
Hammer, Shooting Star, Engulfing, Morning/Evening Star, 3 Soldiers/Crows

Rule-based সবসময় free। Ollama থাকলে AI-powered।

### 5. OFI + CVD
- **OFI**: Real buyer/seller ratio (aggTrades থেকে)
- **CVD**: Price vs volume divergence detect
- **Cross-Basis**: Futures vs Spot gap

---

## ⚙️ config.py — গুরুত্বপূর্ণ Settings

```python
CAPITAL_PER_TRADE_INR = 5000    # ₹5,000 per trade
LEVERAGE_MIN = 15               # Minimum leverage
LEVERAGE_MAX = 20               # Maximum leverage
MIN_RR_RATIO = 2.5              # Minimum risk:reward
DAILY_MAX_SIGNALS = 6           # দিনে max signals
DAILY_MAX_SL_HITS = 3           # এতগুলো SL = signal বন্ধ
MAX_TOTAL_PAIRS = 30            # Max pairs to scan
USE_DELTA_DATA = True           # Delta candle data use করো

# AI Features
REGIME_DETECTION_ENABLED = True
MULTI_AGENT_ENABLED = True
DYNAMIC_PARAMS_ENABLED = True
PATTERN_RECOGNITION_ENABLED = True
SIGNAL_AI_SUPPRESS_LOW_RATING = False  # True করলে C-rating block
```

---

## 🌐 Railway Deploy

1. GitHub এ push করো (`.env` কখনো push করবে না)
2. [railway.app](https://railway.app) → New Project → GitHub repo
3. Settings → Variables → সব `.env` keys add করো
4. Deploy → Health check: `https://your-app.railway.app/health`

---

## 📊 Live Test Plan

**Week 1-2: Paper Trade**
- Bot চালাও, signals note করো
- Real money দিও না
- Win rate track করো

**Week 3+: Live (ছোট করে)**
- শুধু A+ / A rated signals
- Score 85+ signals
- দিনে max ২-৩ trade
- `/sl` `/win` দিয়ে track করো

---

## ⚠️ Risk Warning

Leverage 15-20x মানে ১% price move = 15-20% gain/loss।
SL কখনো remove করবে না।
Bot শুধু signal দেয় — trade এর দায়িত্ব সম্পূর্ণ তোমার।

---

*Arunabha Hybrid Bot v1.0 — Signal-Only Mode*
