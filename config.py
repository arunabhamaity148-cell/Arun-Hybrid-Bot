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
