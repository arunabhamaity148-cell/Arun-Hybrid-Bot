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
# 1h FVG pass korle higher conviction. Na korle signal weak marka.
# MULTITF_FVG_REQUIRED = True mane 1h FVG mandatory, False mane warn only (don't block)
MULTITF_FVG_REQUIRED: bool = False        # False = warn but never hard block
FVG_1H_LOOKBACK: int = 15                 # 1h candles e kototuku pechone dekhbo

# ─── Pullback Quality Filter (NEW) ───────────────────────────────────────────
# Pump peak theke current price kototuku nemeche — Fibonacci golden zone check.
# 30%-62% retracement = ideal entry zone
# < 30% = too shallow (pump still live, chasing)
# > 78% = structure broken, skip
PULLBACK_MIN_PCT: float = 30.0
PULLBACK_MAX_PCT: float = 62.0
PULLBACK_LOOKBACK_CANDLES: int = 96       # 15m * 96 = last 24hr e peak khunjo
# Core pairs er jonno skip (BTC/ETH steady trend, single pump nature na)
PULLBACK_SKIP_CORE_PAIRS: bool = True

# ─── Pump Age Filter (NEW) ────────────────────────────────────────────────────
# Gainer coin er pump kotokhon age shuru hoyeche.
# Fresh pump (< 2hr) = momentum alive, entry safe
# Old pump (> 2hr) = late entry risk, bag holder territory
# 15m candles: 8 candles = 2 hours
PUMP_AGE_MAX_CANDLES: int = 8             # 15m * 8 = max 2 ghanta age pump shuru
PUMP_IDENTIFY_VOL_MULTIPLIER: float = 2.5 # pump candle identify korte 2.5x avg volume
PUMP_AGE_SKIP_CORE_PAIRS: bool = True     # Core pairs skip (no single pump candle expected)

# ─── Relative Volume Score (NEW) ─────────────────────────────────────────────
# 2-layer volume check — coarse 20-day avg replace kore smarter logic
# Layer 1 (1h): Last 1h volume vs same hour yesterday
# Layer 2 (15m): Last 15m candle vs recent 5-candle avg
# Both HIGH = real accumulation (strong signal)
# One HIGH = marginal (continue with warning)
# Both LOW = skip
RELVOL_1H_MIN_MULTIPLIER: float = 1.5    # 1h: 1.5x yesterday same hour
RELVOL_15M_MIN_MULTIPLIER: float = 1.8   # 15m: 1.8x recent 5-candle avg
# Gainer pairs er jonno strict (already pumped, volume continuation must be real)
RELVOL_GAINER_1H_MULTIPLIER: float = 2.0
RELVOL_GAINER_15M_MULTIPLIER: float = 2.0

# ─── Sell Pressure Filter (NEW) ──────────────────────────────────────────────
# Pullback candle quality check — distribution vs healthy retracement.
#
# Check 1 — Vol ratio: avg pullback vol / strongest pump candle vol
#   >= SELL_PRESSURE_VOL_RATIO_MAX → heavy selling during pullback → skip
#   0.8 = pullback avg volume must be < 80% of pump candle volume
#
# Check 2 — Counter-body dominance: fraction of pullback candles with large body
#   > SELL_PRESSURE_RED_BODY_MAX → sellers in control → skip
#   0.6 = max 60% of pullback candles can be strong counter-direction candles

SELL_PRESSURE_VOL_RATIO_MAX: float = 0.8
SELL_PRESSURE_RED_BODY_MAX: float = 0.6
SELL_PRESSURE_LOOKBACK_CANDLES: int = 5
SELL_PRESSURE_SKIP_CORE_PAIRS: bool = True

# ─── Fear & Greed Signal Rules (NEW) ─────────────────────────────────────────
# Direction-aware F&G blocking. Old logic was: F&G < 20 = warn only.
# New logic:
#
#   F&G 0–9   → Capitulation:  LONG allowed (contrarian) ✅  SHORT allowed ✅
#   F&G 10–19 → Extreme Fear:  LONG BLOCKED ❌               SHORT allowed ✅
#   F&G 20–79 → Normal:        LONG allowed ✅               SHORT allowed ✅
#   F&G 80–89 → Extreme Greed: LONG allowed ✅               SHORT BLOCKED ❌
#   F&G 90–100→ Euphoria:      LONG allowed ✅               SHORT allowed (contrarian) ✅

FEAR_GREED_LONG_MIN: int = 20
FEAR_GREED_SHORT_MAX: int = 80
FEAR_GREED_CAPITULATION_THRESHOLD: int = 10
FEAR_GREED_EUPHORIA_THRESHOLD: int = 90
FEAR_GREED_DIRECTION_FILTER: bool = True
