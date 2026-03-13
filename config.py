"""
config.py — Arunabha Hybrid Bot v1.0 — Full Configuration
সব settings এখানে। .env file এ secrets রাখো।
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# 🔑 API KEYS & SECRETS
# ═══════════════════════════════════════════════════════════════════════════════

# Binance (data source — read only, no trading)
BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET:  str = os.getenv("BINANCE_SECRET",  "")

# Delta Exchange (তুমি এখানে trade করো — read only)
DELTA_API_KEY: str = os.getenv("DELTA_API_KEY", "")
DELTA_SECRET:  str = os.getenv("DELTA_SECRET",  "")

# Telegram Bot
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID:   str = os.getenv("TELEGRAM_CHAT_ID",   "")

# CoinGecko (free tier চলবে, Pro key দিলে faster)
COINGECKO_API_KEY: str = os.getenv("COINGECKO_API_KEY", "")

# CryptoPanic (free tier — token দিলে more data)
# Free token: cryptopanic.com/developers/api/
NEWS_CRYPTOPANIC_TOKEN: str = os.getenv("CRYPTOPANIC_TOKEN", "")

# CoinMarketCap (optional — free 10,000 calls/month)
# Free key: coinmarketcap.com/api/
CMC_API_KEY: str = os.getenv("CMC_API_KEY", "")

# OpenAI (gpt-4o-mini — ~$0.0002 per signal, $4 দিয়ে ~20,000 signals)
# Priority: OpenAI → Ollama → Rule-based fallback
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL:   str = "gpt-4o-mini"   # সবচেয়ে সস্তা + accurate

# ═══════════════════════════════════════════════════════════════════════════════
# 🤖 AI SIGNAL RATING
# ═══════════════════════════════════════════════════════════════════════════════

# Signal rating on/off
SIGNAL_AI_RATING_ENABLED: bool = True

# C-rated signal suppress করবে কিনা
# False = সব signal পাঠাবে, rating শুধু দেখাবে (শুরুতে False রাখো)
# True  = C rating signal Telegram এ যাবে না
SIGNAL_AI_SUPPRESS_LOW_RATING: bool = False

# Ollama local LLM (optional, সম্পূর্ণ free)
# Install: ollama.ai → ollama pull mistral → OLLAMA_ENABLED = True করো
OLLAMA_ENABLED: bool = False
OLLAMA_URL:     str  = "http://localhost:11434"
OLLAMA_MODEL:   str  = "mistral"   # বা "llama3"

# ═══════════════════════════════════════════════════════════════════════════════
# 📊 DATA SOURCE
# ═══════════════════════════════════════════════════════════════════════════════

# True  = Delta Exchange candle data (Delta তে trade করো, তাই accurate)
# False = শুধু Binance data
USE_DELTA_DATA: bool = True

# Binance REST endpoints (failover)
BINANCE_REST_ENDPOINTS: list[str] = [
    "https://fapi.binance.com",
    "https://fapi.binance.com",
]

BINANCE_WS_ENDPOINTS: list[str] = [
    "wss://fstream.binance.com",
    "wss://fstream-auth.binance.com",
]

# ═══════════════════════════════════════════════════════════════════════════════
# ⏱️ SCAN SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

# কত সেকেন্ড পর পর scan করবে (300 = 5 মিনিট)
SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))

# CoinGecko market cap / trending কত সেকেন্ড পর refresh
COINGECKO_REFRESH_SECONDS: int = int(os.getenv("COINGECKO_REFRESH_SECONDS", "3600"))

# ═══════════════════════════════════════════════════════════════════════════════
# 📋 PAIR SELECTION
# ═══════════════════════════════════════════════════════════════════════════════

# সবসময় scan হবে এই core pairs
CORE_PAIRS: list[str] = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"
]

# Dynamic pair filters
MIN_24H_CHANGE_PCT:        float = float(os.getenv("MIN_24H_CHANGE_PCT", "7.0"))
MIN_VOLUME_MULTIPLIER:     float = float(os.getenv("MIN_VOLUME_MULTIPLIER", "3.0"))
MIN_MARKET_CAP_USD:        float = float(os.getenv("MIN_MARKET_CAP_USD", "50000000"))
VOLUME_ANOMALY_MULTIPLIER: float = float(os.getenv("VOLUME_ANOMALY_MULTIPLIER", "5.0"))

MAX_GAINER_PAIRS:   int = 5
MAX_TRENDING_PAIRS: int = 3
MAX_TOTAL_PAIRS:    int = 13

# ═══════════════════════════════════════════════════════════════════════════════
# 🎯 SIGNAL FILTERS — CORE
# ═══════════════════════════════════════════════════════════════════════════════

# Minimum Risk:Reward — এর নিচে signal দেবে না
MIN_RR_RATIO: float = float(os.getenv("MIN_RR_RATIO", "2.5"))

# SL buffer — grab level এর নিচে এতটুকু extra
SL_BUFFER_PCT: float = 0.002   # 0.2%

# FVG entry tolerance
FVG_ENTRY_TOLERANCE_PCT: float = 0.003   # 0.3%

# CHoCH confirmation volume
CHOCH_VOLUME_MULTIPLIER: float = 2.0

# Liquidity grab detection
LIQUIDITY_LOOKBACK:       int = 50
LIQUIDITY_RECENT_CANDLES: int = 5
SWING_LEFT_BARS:          int = 3
SWING_RIGHT_BARS:         int = 3

# FVG lookback candles
FVG_LOOKBACK: int = 10

# FVG optional — True হলে FVG না পেলেও CHoCH level এ signal দেবে
FVG_OPTIONAL: bool = True

# ═══════════════════════════════════════════════════════════════════════════════
# 🔗 F4: MULTI-TF FVG CONFLUENCE
# ═══════════════════════════════════════════════════════════════════════════════

# 15m FVG এর সাথে 1h FVG confluence check
# False = warn করে কিন্তু block করে না (recommended)
# True  = 1h FVG mandatory hard block
MULTITF_FVG_REQUIRED: bool = False
FVG_1H_LOOKBACK:      int  = 15

# ═══════════════════════════════════════════════════════════════════════════════
# 📐 F4B: PULLBACK QUALITY — WARN ONLY (never blocks)
# ═══════════════════════════════════════════════════════════════════════════════

# Pump peak থেকে Fibonacci golden zone retracement
# 30%–62% = ideal entry
# <30%     = too shallow (pump still live, chasing)
# >78%     = structure broken
PULLBACK_MIN_PCT:          float = 30.0
PULLBACK_MAX_PCT:          float = 62.0
PULLBACK_LOOKBACK_CANDLES: int   = 96    # 15m × 96 = last 24 hours
PULLBACK_SKIP_CORE_PAIRS:  bool  = True  # BTC/ETH এ skip

# ═══════════════════════════════════════════════════════════════════════════════
# ⏰ F4C: PUMP AGE — WARN ONLY (never blocks)
# ═══════════════════════════════════════════════════════════════════════════════

# Fresh pump (< 2hr) = momentum alive = better entry
PUMP_AGE_MAX_CANDLES:          int   = 8    # 15m × 8 = 2 ঘন্টা
PUMP_IDENTIFY_VOL_MULTIPLIER:  float = 2.5
PUMP_AGE_SKIP_CORE_PAIRS:      bool  = True

# ═══════════════════════════════════════════════════════════════════════════════
# 📊 F4D: RELATIVE VOLUME — HARD BLOCK
# ═══════════════════════════════════════════════════════════════════════════════

# 2-layer volume check
RELVOL_1H_MIN_MULTIPLIER:     float = 1.5   # 1h: গতকাল same hour এর 1.5x
RELVOL_15M_MIN_MULTIPLIER:    float = 1.8   # 15m: recent 5-candle avg এর 1.8x
RELVOL_GAINER_1H_MULTIPLIER:  float = 2.0   # Gainer pairs এ strict
RELVOL_GAINER_15M_MULTIPLIER: float = 2.0

# ═══════════════════════════════════════════════════════════════════════════════
# 📉 F4E: SELL PRESSURE — HARD BLOCK
# ═══════════════════════════════════════════════════════════════════════════════

SELL_PRESSURE_VOL_RATIO_MAX:    float = 0.8  # pullback avg vol < 80% of pump candle
SELL_PRESSURE_RED_BODY_MAX:     float = 0.6  # max 60% strong counter-candles
SELL_PRESSURE_LOOKBACK_CANDLES: int   = 5
SELL_PRESSURE_SKIP_CORE_PAIRS:  bool  = True

# ═══════════════════════════════════════════════════════════════════════════════
# 💸 F4F: FUNDING RATE — HARD BLOCK
# ═══════════════════════════════════════════════════════════════════════════════

#   +0.10% বা বেশি → সবাই LONG  → LONG block
#   -0.10% বা কম  → সবাই SHORT → SHORT block
#   ±0.04% এর মধ্যে → Neutral  → দুটোই allow
#   Opposite crowding → contrarian HIGH CONVICTION ✅

FUNDING_EXTREME_THRESHOLD: float = 0.10
FUNDING_HIGH_THRESHOLD:    float = 0.04
FUNDING_FILTER_ENABLED:    bool  = True

# ═══════════════════════════════════════════════════════════════════════════════
# 📰 F0: NEWS SENTIMENT — HARD BLOCK
# ═══════════════════════════════════════════════════════════════════════════════

# Context-aware sentiment (TextBlob-style) — "SEC launch investigation" ≠ bullish
NEWS_SENTIMENT_ENABLED:   bool  = True
NEWS_SENTIMENT_THRESHOLD: float = 3.0   # net score এর উপরে block
NEWS_CACHE_MINUTES:       int   = 15

# ═══════════════════════════════════════════════════════════════════════════════
# 📈 F1: BTC REGIME — HARD BLOCK
# ═══════════════════════════════════════════════════════════════════════════════

BTC_1H_BIAS_ENABLED: bool = True

# ═══════════════════════════════════════════════════════════════════════════════
# 😨 FEAR & GREED DIRECTION FILTER
# ═══════════════════════════════════════════════════════════════════════════════

#   F&G  0– 9  → Capitulation  → LONG ✅ SHORT ✅ (contrarian)
#   F&G 10–19  → Extreme Fear  → LONG ❌ SHORT ✅
#   F&G 20–79  → Normal        → LONG ✅ SHORT ✅
#   F&G 80–89  → Extreme Greed → LONG ✅ SHORT ❌
#   F&G 90–100 → Euphoria      → LONG ✅ SHORT ✅ (contrarian)

FEAR_GREED_LONG_MIN:               int  = 20
FEAR_GREED_SHORT_MAX:              int  = 80
FEAR_GREED_CAPITULATION_THRESHOLD: int  = 10
FEAR_GREED_EUPHORIA_THRESHOLD:     int  = 90
FEAR_GREED_DIRECTION_FILTER:       bool = True
FEAR_GREED_CAUTION_THRESHOLD:      int  = 20

# ═══════════════════════════════════════════════════════════════════════════════
# 🛡️ DAILY PROTECTION
# ═══════════════════════════════════════════════════════════════════════════════

DAILY_MAX_SIGNALS:            int = 6    # দিনে max signal
DAILY_MAX_SL_HITS:            int = 3    # এতগুলো SL = বাকি দিন বন্ধ
CONSECUTIVE_SL_PAUSE:         int = 2    # পরপর এতগুলো SL = pause
CONSECUTIVE_SL_PAUSE_MINUTES: int = 30

# ═══════════════════════════════════════════════════════════════════════════════
# 💰 POSITION SIZING
# ═══════════════════════════════════════════════════════════════════════════════

# প্রতি trade এ fixed margin — সবসময় ₹5,000
CAPITAL_PER_TRADE_INR: int = 5000

# Leverage — signal score দেখে decide হয়:
#   Score 80+  → LEVERAGE_MAX (20x) 🔥
#   Score 65+  → 17x
#   Score 50+  → LEVERAGE_MIN (15x)
#   Score <50  → skip suggestion
LEVERAGE_MIN: int = 15
LEVERAGE_MAX: int = 20

# ═══════════════════════════════════════════════════════════════════════════════
# 🕐 SESSION FILTER
# ═══════════════════════════════════════════════════════════════════════════════

SESSION_FILTER_ENABLED: bool = True
DEAD_ZONE_START_HOUR:   int  = 1    # IST 01:00 — dead zone শুরু
DEAD_ZONE_END_HOUR:     int  = 7    # IST 07:00 — dead zone শেষ

# একই pair এ পরপর signal এর মাঝে minimum wait
SIGNAL_COOLDOWN_MINUTES: int = 30

# ═══════════════════════════════════════════════════════════════════════════════
# ⚙️ MISC
# ═══════════════════════════════════════════════════════════════════════════════

PORT:      int = int(os.getenv("PORT", "8080"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
TIMEZONE:  str = "Asia/Kolkata"

MIN_PRICE_USD: float = 0.001

WS_MAX_RECONNECT_ATTEMPTS: int   = 10
WS_RECONNECT_BASE_DELAY:   float = 1.0
WS_HEARTBEAT_INTERVAL:     int   = 20

# Unused — placeholder
COINDCX_API_KEY: str = os.getenv("COINDCX_API_KEY", "")
COINDCX_SECRET:  str = os.getenv("COINDCX_SECRET",  "")
