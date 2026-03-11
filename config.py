"""
config.py — Centralised configuration for Arunabha Hybrid Bot v1.0
All settings loaded from environment variables with sane defaults.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Exchange credentials ───────────────────────────────────────────────────

BINANCE_API_KEY: str = os.getenv("BINANCE_API_KEY", "")
BINANCE_SECRET: str = os.getenv("BINANCE_SECRET", "")

COINDCX_API_KEY: str = os.getenv("COINDCX_API_KEY", "")
COINDCX_SECRET: str = os.getenv("COINDCX_SECRET", "")

DELTA_API_KEY: str = os.getenv("DELTA_API_KEY", "")
DELTA_SECRET: str = os.getenv("DELTA_SECRET", "")

COINGECKO_API_KEY: str = os.getenv("COINGECKO_API_KEY", "")

# ─── Telegram ───────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Scan settings ──────────────────────────────────────────────────────────

SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
COINGECKO_REFRESH_SECONDS: int = int(os.getenv("COINGECKO_REFRESH_SECONDS", "3600"))

# ─── Dynamic pair filters ────────────────────────────────────────────────────

MIN_24H_CHANGE_PCT: float = float(os.getenv("MIN_24H_CHANGE_PCT", "7.0"))
MIN_VOLUME_MULTIPLIER: float = float(os.getenv("MIN_VOLUME_MULTIPLIER", "3.0"))
MIN_MARKET_CAP_USD: float = float(os.getenv("MIN_MARKET_CAP_USD", "50000000"))
VOLUME_ANOMALY_MULTIPLIER: float = float(os.getenv("VOLUME_ANOMALY_MULTIPLIER", "5.0"))

# ─── Signal filters ──────────────────────────────────────────────────────────

MIN_RR_RATIO: float = float(os.getenv("MIN_RR_RATIO", "2.5"))
SL_BUFFER_PCT: float = 0.002
FVG_ENTRY_TOLERANCE_PCT: float = 0.003
CHOCH_VOLUME_MULTIPLIER: float = 2.0
LIQUIDITY_LOOKBACK: int = 50
LIQUIDITY_RECENT_CANDLES: int = 5
SWING_LEFT_BARS: int = 3
SWING_RIGHT_BARS: int = 3
FVG_LOOKBACK: int = 10

# ─── Pair limits ─────────────────────────────────────────────────────────────

CORE_PAIRS: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]
MAX_GAINER_PAIRS: int = 5
MAX_TRENDING_PAIRS: int = 3
MAX_TOTAL_PAIRS: int = 13

# ─── Binance API endpoints ────────────────────────────────────────────────────

BINANCE_REST_ENDPOINTS: list[str] = [
    "https://fapi.binance.com",
    "https://fapi.binance.com",
]

BINANCE_WS_ENDPOINTS: list[str] = [
    "wss://fstream.binance.com",
    "wss://fstream-auth.binance.com",
]

# ─── Misc ────────────────────────────────────────────────────────────────────

PORT: int = int(os.getenv("PORT", "8080"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
TIMEZONE: str = "Asia/Kolkata"

FEAR_GREED_CAUTION_THRESHOLD: int = 20
MIN_PRICE_USD: float = 0.001

WS_MAX_RECONNECT_ATTEMPTS: int = 10
WS_RECONNECT_BASE_DELAY: float = 1.0
WS_HEARTBEAT_INTERVAL: int = 20

# ─── Session Filter ───────────────────────────────────────────────────────────

DEAD_ZONE_START_HOUR: int = 1
DEAD_ZONE_END_HOUR: int = 7
SESSION_FILTER_ENABLED: bool = True

# ─── Signal Cooldown ──────────────────────────────────────────────────────────

SIGNAL_COOLDOWN_MINUTES: int = 30

# ─── FVG Optional Mode ───────────────────────────────────────────────────────

FVG_OPTIONAL: bool = True

# ─── Multi-TF FVG (NEW) ───────────────────────────────────────────────────────
# 15m FVG er sathe 1h FVG o check kora hobe confluence er jonno.
# 1h FVG pass korle higher conviction. Na korle signal weak marka dewa hobe.
# MULTITF_FVG_REQUIRED = True mane 1h FVG mandatory, False mane optional (warn only)
MULTITF_FVG_REQUIRED: bool = False        # False = warn but don't block
FVG_1H_LOOKBACK: int = 15                 # 1h candles e kototuku pechone dekhbo

# ─── Pullback Quality Filter (NEW) ───────────────────────────────────────────
# Pump peak theke current price kototuku nemeche.
# 30%-62% retracement = ideal FVG/OB zone (Fibonacci golden zone)
# < 30% = too shallow, price ekhono pump e ache, risky entry
# > 78% = structure likely broken, skip
PULLBACK_MIN_PCT: float = 30.0            # minimum retracement %
PULLBACK_MAX_PCT: float = 62.0            # maximum retracement %
PULLBACK_LOOKBACK_CANDLES: int = 96       # 15m * 96 = last 24 hours e peak khunjo
# Core pairs (BTC/ETH etc) er jonno pullback filter skip korbo
# Karon core pairs pump-dump nature na, steady trend e thake
PULLBACK_SKIP_CORE_PAIRS: bool = True

# ─── Pump Age Filter (NEW) ────────────────────────────────────────────────────
# Gainer coin er pump kotokhon age shuru hoyeche seta check kore.
# Niye pump = fresh momentum, trade newa safe
# Purono pump = late entry, bag holding risk
# Candles in 15m: 8 candles = 2 hours
PUMP_AGE_MAX_CANDLES: int = 8             # 15m * 8 = 2 ghanta er modhye pump shuru
# Volume threshold: pump candle ke identify korte minimum volume
PUMP_IDENTIFY_VOL_MULTIPLIER: float = 2.5 # pump candle volume avg er 2.5x hote hobe
# Core pairs er jonno pump age skip (BTC/ETH steady move kore, single pump candle thake na)
PUMP_AGE_SKIP_CORE_PAIRS: bool = True

# ─── Relative Volume Score (NEW) ─────────────────────────────────────────────
# Current logic: aajker volume vs 20-day average — coarse, noise thake
# Better: 2 layer check
#   Layer 1 (1h): Last 1h volume vs same hour yesterday — intraday comparison
#   Layer 2 (15m): Last 15m candle volume vs last 5 candles avg — micro momentum
# Duto layer e HIGH = real accumulation, trade nao
# Ek layer HIGH = marginal, warn but continue
# Duto layer LOW = skip
RELVOL_1H_MIN_MULTIPLIER: float = 1.5    # 1h volume must be 1.5x yesterday same hour
RELVOL_15M_MIN_MULTIPLIER: float = 1.8   # last 15m candle must be 1.8x recent 5-candle avg
# Gainer pairs er jonno strict threshold (already pumped, volume must confirm continuation)
RELVOL_GAINER_1H_MULTIPLIER: float = 2.0
RELVOL_GAINER_15M_MULTIPLIER: float = 2.0
