"""
core/scheduler.py — APScheduler setup for Arunabha Hybrid Bot v1.0
5-min scan | 1-hr refresh | cache cleanup | daily summary at 23:59 IST
"""

import logging
import asyncio
from datetime import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
    return _scheduler


async def _run_scan_safe() -> None:
    from core.engine import engine
    try:
        await engine.run_scan()
    except Exception as exc:
        logger.error(f"Scan job uncaught exception: {exc}", exc_info=True)


async def _run_hourly_safe() -> None:
    from core.engine import engine
    try:
        await engine.run_hourly_tasks()
    except Exception as exc:
        logger.error(f"Hourly job uncaught exception: {exc}", exc_info=True)


async def _cache_cleanup() -> None:
    removed = await cache.clear_expired()
    if removed:
        logger.debug(f"Cache cleanup: removed {removed} expired entries")


async def _daily_summary() -> None:
    from core.engine import engine
    from notification.telegram_bot import telegram_bot
    try:
        signals = engine.get_signals_today()
        now_str = datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d %b %Y")

        if not signals:
            msg = f"📊 <b>Daily Summary — {now_str}</b>\n\nNo signals generated today."
        else:
            lines = [f"📊 <b>Daily Signal Summary — {now_str}</b>", f"Total: {len(signals)} signals\n"]
            for s in signals:
                d_emoji = "🟢" if s["direction"] == "LONG" else "🔴"
                score_str    = f" | 🎯{s['score']}/100" if s.get("score") else ""
                ai_str       = f" | 🤖{s['ai_rating']}" if s.get("ai_rating") and s["ai_rating"] != "N/A" else ""
                lines.append(
                    f"{d_emoji} #{s['num']} {s['symbol']} {s['direction']} "
                    f"| RR {s['rr']:.2f}{score_str}{ai_str} "
                    f"| ⏰ {s['time']}"
                )
            msg = "\n".join(lines)

        await telegram_bot.send_message(msg)
        logger.info(f"Daily summary sent: {len(signals)} signals")
    except Exception as exc:
        logger.error(f"Daily summary failed: {exc}", exc_info=True)


def start_scheduler() -> AsyncIOScheduler:
    scheduler = get_scheduler()

    scheduler.add_job(
        _run_scan_safe,
        trigger=IntervalTrigger(seconds=config.SCAN_INTERVAL_SECONDS),
        id="main_scan",
        name="Main Pair Scan",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )

    scheduler.add_job(
        _run_hourly_safe,
        trigger=IntervalTrigger(seconds=config.COINGECKO_REFRESH_SECONDS),
        id="hourly_refresh",
        name="Hourly CoinGecko Refresh",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    scheduler.add_job(
        _cache_cleanup,
        trigger=IntervalTrigger(minutes=10),
        id="cache_cleanup",
        name="Cache Cleanup",
    )

    scheduler.add_job(
        _daily_summary,
        trigger=CronTrigger(hour=23, minute=59, timezone="Asia/Kolkata"),
        id="daily_summary",
        name="Daily Signal Summary",
        max_instances=1,
    )

    scheduler.start()
    logger.info("✅ Scheduler started — scan every 5min, refresh every 1hr")
    return scheduler
