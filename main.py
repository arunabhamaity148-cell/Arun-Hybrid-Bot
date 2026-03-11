"""
main.py — Entry point for Arunabha Hybrid Bot v1.0
Starts FastAPI health server (for Railway) + bot engine + APScheduler.
Signal-only mode — NO auto trading.
"""

import asyncio
import logging
import sys
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from datetime import datetime
import pytz

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger("main")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

import config

IST = pytz.timezone(config.TIMEZONE)
_start_time = datetime.now(IST)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init engine, Telegram, scheduler. Shutdown: graceful stop."""
    logger.info("════════════════════════════════════════════")
    logger.info("  ARUNABHA HYBRID BOT v1.0 — STARTING UP  ")
    logger.info("════════════════════════════════════════════")
    logger.info(f"  Mode      : SIGNAL ONLY — no auto trading")
    logger.info(f"  Scan      : every {config.SCAN_INTERVAL_SECONDS}s")
    logger.info(f"  CG Refresh: every {config.COINGECKO_REFRESH_SECONDS}s")
    logger.info(f"  Core Pairs: {config.CORE_PAIRS}")
    logger.info("════════════════════════════════════════════")

    from notification.telegram_bot import telegram_bot
    try:
        await telegram_bot.initialise()
    except Exception as exc:
        logger.warning(f"Telegram init failed (continuing without): {exc}")

    from core.engine import engine
    try:
        await engine.startup()
    except Exception as exc:
        logger.error(f"Engine startup error: {exc}", exc_info=True)

    from core.scheduler import start_scheduler
    scheduler = start_scheduler()

    asyncio.create_task(_first_scan())

    yield

    logger.info("Shutting down bot...")
    scheduler.shutdown(wait=False)
    try:
        await engine._volume_watcher.stop()
    except Exception:
        pass
    try:
        await telegram_bot.stop()
    except Exception:
        pass
    logger.info("Bot shutdown complete.")


async def _first_scan() -> None:
    """Run first scan 10 seconds after startup to let everything settle."""
    await asyncio.sleep(10)
    from core.engine import engine
    try:
        await engine.run_scan()
    except Exception as exc:
        logger.error(f"First scan failed: {exc}", exc_info=True)


app = FastAPI(
    title="Arunabha Hybrid Bot v1.0",
    description="Signal-only crypto trading bot. No auto trading.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Railway health check endpoint."""
    from core.engine import engine
    status = engine.get_status_dict()
    uptime_secs = (datetime.now(IST) - _start_time).seconds
    return JSONResponse({
        "status": "ok",
        "bot": "Arunabha Hybrid Bot v1.0",
        "mode": "SIGNAL_ONLY",
        "uptime_seconds": uptime_secs,
        "scan_count": status["scan_count"],
        "signals_today": status["signals_today"],
        "btc_regime": status["btc_regime"],
        "fear_greed": status["fear_greed"],
    })


@app.get("/status")
async def get_status():
    """Detailed status endpoint."""
    from core.engine import engine
    return engine.get_status_dict()


@app.get("/signals")
async def get_signals():
    """Today's signals as JSON."""
    from core.engine import engine
    return {"signals": engine.get_signals_today()}


@app.post("/scan")
async def trigger_scan():
    """Manually trigger a scan (useful for testing)."""
    from core.engine import engine
    asyncio.create_task(engine.run_scan())
    return {"status": "scan_triggered"}


@app.get("/")
async def root():
    return {
        "name": "Arunabha Hybrid Bot v1.0",
        "mode": "SIGNAL_ONLY",
        "warning": "This bot generates signals only. NO auto trading.",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PORT,
        log_level=config.LOG_LEVEL.lower(),
        access_log=False,
    )

