"""
notification/telegram_bot.py — Telegram Bot for Arunabha Hybrid Bot v1.0
Outbound signals + inbound commands: /add /remove /news /status /signals /block /help
"""

import asyncio
import logging
from datetime import datetime
import pytz
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode

import config

logger = logging.getLogger(__name__)
IST = pytz.timezone(config.TIMEZONE)


class TelegramBot:

    def __init__(self):
        self._app: Application | None = None
        self._bot: Bot | None = None
        self._ready = False

    async def initialise(self) -> None:
        if not config.TELEGRAM_BOT_TOKEN:
            logger.warning("No Telegram bot token — Telegram disabled")
            return

        self._app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self._bot = self._app.bot

        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("add", self._cmd_add))
        self._app.add_handler(CommandHandler("remove", self._cmd_remove))
        self._app.add_handler(CommandHandler("news", self._cmd_news))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("signals", self._cmd_signals))
        self._app.add_handler(CommandHandler("block", self._cmd_block))
        self._app.add_handler(CommandHandler("help", self._cmd_help))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        self._ready = True
        logger.info("✅ Telegram bot started and polling")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send_message(self, text: str) -> None:
        if not self._ready or not config.TELEGRAM_CHAT_ID:
            logger.info(f"[TG DISABLED] {text[:120]}")
            return
        try:
            await self._bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            logger.error(f"Telegram send_message failed: {exc}")

    async def _is_authorised(self, update: Update) -> bool:
        if not config.TELEGRAM_CHAT_ID:
            return True
        return str(update.effective_chat.id) == str(config.TELEGRAM_CHAT_ID)

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        await update.message.reply_html(
            "🤖 <b>Arunabha Hybrid Bot v1.0</b>\n\n"
            "Signal-only crypto trading bot.\n"
            "All signals should be executed <b>manually</b> on Delta Exchange.\n\n"
            "Use /help to see all commands."
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        await update.message.reply_html(
            "📋 <b>Available Commands</b>\n\n"
            "/add PEPE — Add PEPE to scan list immediately\n"
            "/remove PEPE — Remove from dynamic scan list\n"
            "/news DOGE — Flag DOGE as news-driven (relaxes volume filter to 1.5x)\n"
            "/block SHIB — Manually block a coin from signals\n"
            "/status — Show current pair list, last scan, BTC regime, F&G\n"
            "/signals — Show today's all signals\n"
            "/help — This message\n\n"
            "⚠️ Bot is <b>signal-only</b> — no auto trading."
        )

    async def _cmd_add(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.scanner import scanner
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: /add PEPE")
            return
        symbol = args[0].upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        scanner.add_manual_pair(symbol)
        await update.message.reply_html(f"✅ <b>{symbol}</b> added to scan list.\nWill be included in next 5-min scan.")
        logger.info(f"Manual add: {symbol}")

    async def _cmd_remove(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.scanner import scanner
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: /remove PEPE")
            return
        symbol = args[0].upper()
        scanner.remove_pair(symbol)
        await update.message.reply_html(f"🗑️ <b>{symbol}</b> removed from dynamic scan list.")

    async def _cmd_news(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.scanner import scanner
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: /news DOGE")
            return
        symbol = args[0].upper()
        scanner.flag_news(symbol)
        await update.message.reply_html(
            f"📰 <b>{symbol}</b> flagged as news-driven.\nVolume filter relaxed to 1.5x for this coin."
        )

    async def _cmd_block(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.scanner import scanner
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: /block SHIB")
            return
        symbol = args[0].upper()
        scanner.block_pair(symbol)
        await update.message.reply_html(f"🚫 <b>{symbol}</b> blocked from signals.")

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        status = engine.get_status_dict()
        sc_status = status["scanner_status"]
        fg = status["fear_greed"]
        now_str = datetime.now(IST).strftime("%H:%M IST, %d %b %Y")
        pairs_line = ", ".join(sc_status["core"] + sc_status["gainers"] + sc_status["trending"])
        blocked = ", ".join(sc_status["blocked"]) or "None"
        news = ", ".join(sc_status["news_flagged"]) or "None"
        anomaly = ", ".join(sc_status["anomaly"]) or "None"

        await update.message.reply_html(
            f"📊 <b>Bot Status</b> — {now_str}\n\n"
            f"🔢 Scans run: {status['scan_count']}\n"
            f"📈 Signals today: {status['signals_today']}\n"
            f"📉 BTC Regime: <b>{status['btc_regime']}</b>\n"
            f"😨 Fear & Greed: {fg['value']} ({fg['value_classification']})\n\n"
            f"📋 Active Pairs:\n<code>{pairs_line}</code>\n\n"
            f"⚡ Volume Anomalies: {anomaly}\n"
            f"📰 News Flagged: {news}\n"
            f"🚫 Blocked: {blocked}"
        )

    async def _cmd_signals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        signals = engine.get_signals_today()

        if not signals:
            await update.message.reply_text("No signals generated today yet.")
            return

        lines = [f"📊 <b>Today's Signals ({len(signals)} total)</b>\n"]
        for s in signals:
            d_emoji = "🟢" if s["direction"] == "LONG" else "🔴"
            lines.append(
                f"{d_emoji} #{s['num']} {s['symbol']} {s['direction']} | "
                f"Entry: {s['entry']:.8g} | "
                f"TP1: {s['tp1']:.8g} | "
                f"SL: {s['sl']:.8g} | "
                f"RR: {s['rr']:.1f} | "
                f"⏰ {s['time']}"
            )
        await update.message.reply_html("\n".join(lines))


telegram_bot = TelegramBot()
