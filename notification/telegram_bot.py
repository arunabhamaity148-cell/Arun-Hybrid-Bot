"""
notification/telegram_bot.py — Telegram Bot for Arunabha Hybrid Bot v1.0
Outbound signals + inbound commands.

Commands:
  /start        — Bot info + feature list
  /help         — All commands
  /status       — Bot status, BTC regime, F&G, SL hits
  /signals      — Today's signals (score/160 + AI rating)
  /scan         — Manual scan trigger
  /score        — Score system explain (0-160)
  /regime       — Current market regime detect
  /perf         — Win/loss performance summary
  /pattern SYM  — Latest candle patterns
  /ofi SYM      — Order Flow analysis (OFI + CVD)
  /add SYM      — Pair scan list এ add করো
  /remove SYM   — List থেকে remove করো
  /news SYM     — News-driven coin flag করো
  /block SYM    — Signal block করো
  /backtest     — Backtest চালাও
  /sl           — SL hit report
  /tp1          — TP1 partial exit report
  /win          — Full win/TP report
  /reset        — Daily counters reset
"""

import asyncio
import logging
from datetime import datetime, timedelta
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

        handlers = [
            ("start",    self._cmd_start),
            ("help",     self._cmd_help),
            ("status",   self._cmd_status),
            ("signals",  self._cmd_signals),
            ("scan",     self._cmd_scan),
            ("score",    self._cmd_score),
            ("regime",   self._cmd_regime),
            ("perf",     self._cmd_perf),
            ("pattern",  self._cmd_pattern),
            ("ofi",      self._cmd_ofi),
            ("add",      self._cmd_add),
            ("remove",   self._cmd_remove),
            ("news",     self._cmd_news),
            ("block",    self._cmd_block),
            ("backtest", self._cmd_backtest),
            ("sl",       self._cmd_sl),
            ("tp1",      self._cmd_tp1),
            ("win",      self._cmd_win),
            ("reset",    self._cmd_reset_daily),
        ]
        for cmd, handler in handlers:
            self._app.add_handler(CommandHandler(cmd, handler))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        self._ready = True
        logger.info("Telegram bot started and polling")

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

    # ── /start ────────────────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        await update.message.reply_html(
            "🤖 <b>Arunabha Hybrid Bot v1.0</b>\n\n"
            "Advanced Signal-Only Crypto Trading Bot\n"
            "Exchange: <b>Delta Exchange</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 <b>AI Features:</b>\n"
            "• Regime Detection (Markup/Distribution/...)\n"
            "• Multi-Agent Cross-Check (Bull vs Bear)\n"
            "• ATR Dynamic SL/TP\n"
            "• Candle Pattern Recognition\n"
            "• OFI + CVD Order Flow Analysis\n"
            "• Cross-Exchange Basis (Futures vs Spot)\n\n"
            "📊 Signal Score: <b>0-160</b>\n"
            "💎 130+ = Elite  |  🔥 110+ = High Conviction\n"
            "✅ 85+ = Good    |  ⚠️ 65+ = Moderate\n\n"
            "⚠️ <b>Signal-only — সব trade manually execute করো</b>\n\n"
            "/help — সব commands দেখো"
        )

    # ── /help ─────────────────────────────────────────────────────────────────

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        await update.message.reply_html(
            "📋 <b>Arunabha Hybrid Bot — Commands</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>📊 Scan Control</b>\n"
            "/scan — এখনই manual scan trigger করো\n"
            "/add PEPE — Pair scan list এ add করো\n"
            "/remove PEPE — List থেকে remove করো\n"
            "/news DOGE — News-driven coin flag করো\n"
            "/block SHIB — এই coin এ signal বন্ধ করো\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>📈 Stats & Info</b>\n"
            "/status — Bot status, BTC regime, F&G\n"
            "/signals — আজকের সব signals (score + AI)\n"
            "/score — Score system explain (0-160)\n"
            "/regime — Current market regime দেখাও\n"
            "/perf — Win/loss performance summary\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>🔬 Analysis</b>\n"
            "/pattern SOLUSDT — Latest candle patterns\n"
            "/ofi SOLUSDT — Order Flow (OFI + CVD)\n"
            "/backtest SOLUSDT 30 — 30-day backtest\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>📉 Trade Tracking</b>\n"
            "/sl — SL hit report করো\n"
            "/tp1 — TP1 partial exit report\n"
            "/win — Full TP hit report করো\n"
            "/reset — Daily counters reset করো\n\n"
            "⚠️ Signal-only — Delta Exchange এ manually execute করো"
        )

    # ── /status ───────────────────────────────────────────────────────────────

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        status    = engine.get_status_dict()
        sc_status = status["scanner_status"]
        fg        = status["fear_greed"]
        now_str   = datetime.now(IST).strftime("%H:%M IST, %d %b %Y")

        pairs_line = ", ".join(
            sc_status["core"] + sc_status["gainers"] + sc_status["trending"]
        )
        blocked = ", ".join(sc_status["blocked"]) or "None"
        news_fl = ", ".join(sc_status["news_flagged"]) or "None"
        anomaly = ", ".join(sc_status["anomaly"]) or "None"

        pause_str = ""
        if engine._pause_until:
            pause_str = (
                f"\n⏸️ Pause until: {engine._pause_until.strftime('%H:%M IST')}"
            )

        await update.message.reply_html(
            f"📊 <b>Bot Status</b> — {now_str}\n\n"
            f"🔢 Scans run: {status['scan_count']}\n"
            f"📈 Signals today: {status['signals_today']}\n"
            f"🔴 SL hits today: {engine._daily_sl_hits}/{config.DAILY_MAX_SL_HITS}\n"
            f"📉 BTC Regime: <b>{status['btc_regime']}</b>\n"
            f"😨 Fear & Greed: {fg['value']} ({fg['value_classification']})"
            f"{pause_str}\n\n"
            f"📋 <b>Active Pairs ({config.MAX_TOTAL_PAIRS} max):</b>\n"
            f"<code>{pairs_line}</code>\n\n"
            f"⚡ Volume Anomalies: {anomaly}\n"
            f"📰 News Flagged: {news_fl}\n"
            f"🚫 Blocked: {blocked}"
        )

    # ── /signals ──────────────────────────────────────────────────────────────

    async def _cmd_signals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        signals = engine.get_signals_today()

        if not signals:
            await update.message.reply_text("আজকে এখনো কোনো signal আসেনি।")
            return

        lines = [f"📊 <b>Today's Signals ({len(signals)} total)</b>\n"]
        for s in signals:
            d_emoji   = "🟢" if s["direction"] == "LONG" else "🔴"
            score_str = f" | 🎯{s.get('score', '?')}/160" if s.get("score") else ""
            ai_str    = (
                f" | 🤖{s.get('ai_rating', '')}"
                if s.get("ai_rating") and s.get("ai_rating") != "N/A"
                else ""
            )
            lines.append(
                f"{d_emoji} #{s['num']} <b>{s['symbol']}</b> {s['direction']} | "
                f"Entry: <code>{s['entry']:.6g}</code> | "
                f"RR: {s['rr']:.1f}{score_str}{ai_str} | "
                f"⏰ {s['time']}"
            )
        await update.message.reply_html("\n".join(lines))

    # ── /scan ─────────────────────────────────────────────────────────────────

    async def _cmd_scan(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        await update.message.reply_text("🔍 Manual scan শুরু হচ্ছে...")
        asyncio.create_task(engine.run_scan())

    # ── /score ────────────────────────────────────────────────────────────────

    async def _cmd_score(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        await update.message.reply_html(
            "🎯 <b>Signal Score System (0-160)</b>\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Base Score (0-100):</b>\n"
            "• RR Quality        → max 30 pts\n"
            "• Multi-TF FVG      → max 20 pts\n"
            "• Funding Rate      → max 15 pts\n"
            "• Fear &amp; Greed  → max 15 pts\n"
            "• Trading Session   → max 10 pts\n"
            "• Warn Filters      → max 10 pts\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Advanced Bonuses (up to +60):</b>\n"
            "• OFI + CVD + Flow    → max +25 pts\n"
            "• Regime Detection    → -5 to +10 pts\n"
            "• Multi-Agent Check   → -8 to +8 pts\n"
            "• Pattern Recognition → -5 to +8 pts\n"
            "• Cross-Exchange Basis → max +5 pts\n"
            "• Liq Heatmap + TOD   → max +5 pts\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "<b>Score Labels:</b>\n"
            "💎 130+ = Elite Setup    (20x)\n"
            "🔥🔥 110+ = High Conv.  (20x)\n"
            "🔥 85+ = Good Setup     (17x)\n"
            "✅ 65+ = Moderate       (15x)\n"
            "⚠️ 50+ = Caution\n"
            "❗ &lt;50 = Weak — skip recommended"
        )

    # ── /regime ───────────────────────────────────────────────────────────────

    async def _cmd_regime(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        await update.message.reply_text("🌍 Regime detect করছি...")
        try:
            from core.engine import engine
            from core.ai_regime import get_regime
            from data.coingecko_client import coingecko

            status     = engine.get_status_dict()
            btc_regime = status["btc_regime"]
            fg_data    = await coingecko.get_fear_greed()
            fg_val     = fg_data.get("value", 50)

            regime = await get_regime(
                symbol="BTCUSDT",
                direction="LONG",
                btc_regime=btc_regime,
                fg_val=fg_val,
            )

            phase_emoji = {
                "ACCUMULATION": "📦", "MARKUP": "🚀",
                "DISTRIBUTION": "🏭", "MARKDOWN": "📉",
                "UNKNOWN": "❓"
            }.get(regime.phase, "❓")

            await update.message.reply_html(
                f"🌍 <b>Market Regime</b>\n\n"
                f"{phase_emoji} Phase: <b>{regime.phase}</b>\n"
                f"📊 Confidence: {regime.confidence}%\n"
                f"🎯 Bias: {regime.bias}\n"
                f"💡 Reason: {regime.reasoning}\n\n"
                f"Score Impact: {regime.signal_boost:+d} pts\n"
                f"⚠️ Caution: {'Yes — check direction!' if regime.caution else 'No'}"
            )
        except Exception as exc:
            await update.message.reply_text(f"Regime detection failed: {exc}")

    # ── /perf ─────────────────────────────────────────────────────────────────

    async def _cmd_perf(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        sl_hits   = engine._daily_sl_hits
        sig_count = engine._daily_signals_sent
        wins      = max(0, sig_count - sl_hits)

        if sig_count == 0:
            await update.message.reply_text("আজকে এখনো কোনো signal নেই।")
            return

        win_rate   = wins / sig_count * 100
        status_str = (
            "✅ Good day"      if win_rate >= 60 else
            "⚠️ Mixed day"    if win_rate >= 40 else
            "🔴 Tough day"
        )

        await update.message.reply_html(
            f"📈 <b>Today's Performance</b>\n\n"
            f"Signals sent: {sig_count}\n"
            f"SL hits: {sl_hits}\n"
            f"Wins (est): {wins}\n"
            f"Win rate: {win_rate:.0f}%\n\n"
            f"Status: {status_str}\n\n"
            f"<i>Use /sl and /win to update counters accurately.</i>"
        )

    # ── /pattern SYM ──────────────────────────────────────────────────────────

    async def _cmd_pattern(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        args   = ctx.args
        symbol = args[0].upper() if args else "BTCUSDT"
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        await update.message.reply_text(f"🕯️ {symbol} patterns দেখছি...")
        try:
            from data.binance_client import binance
            from data.pattern_recognition import get_patterns

            df = await binance.get_klines(symbol, "15m", limit=15)
            candles = df.tail(8).to_dict("records") if df is not None and not df.empty else []

            r_long  = await get_patterns(symbol, "LONG",  candles)
            r_short = await get_patterns(symbol, "SHORT", candles)

            patterns_str = ", ".join(r_long.patterns_found) or "No major patterns"

            await update.message.reply_html(
                f"🕯️ <b>Candle Patterns — {symbol}</b>\n\n"
                f"Patterns found: <b>{patterns_str}</b>\n\n"
                f"🟢 LONG view:  {r_long.pattern_label} "
                f"({r_long.reliability}% hist.) [{r_long.score_bonus:+d} pts]\n"
                f"🔴 SHORT view: {r_short.pattern_label} "
                f"({r_short.reliability}% hist.) [{r_short.score_bonus:+d} pts]\n\n"
                f"<i>Based on last 8 × 15m candles</i>"
            )
        except Exception as exc:
            await update.message.reply_text(f"Pattern analysis failed: {exc}")

    # ── /ofi SYM ──────────────────────────────────────────────────────────────

    async def _cmd_ofi(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        args   = ctx.args
        symbol = args[0].upper() if args else "BTCUSDT"
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        await update.message.reply_text(f"⚡ {symbol} Order Flow দেখছি...")
        try:
            from data.ofi_cvd import get_ofi_cvd
            from data.binance_client import binance
            from data.cross_basis import get_cross_basis

            price = await binance.get_price(symbol)
            ofi_res, basis_res = await asyncio.gather(
                get_ofi_cvd(
                    symbol=symbol, direction="LONG",
                    current_price=price or 0
                ),
                get_cross_basis(symbol, "LONG"),
                return_exceptions=True,
            )

            lines = [f"⚡ <b>Order Flow — {symbol}</b>\n"]

            if isinstance(ofi_res, Exception) or ofi_res is None:
                lines.append("OFI: Data unavailable")
            else:
                lines.append(f"OFI Ratio: <b>{ofi_res.ofi_ratio:+.3f}</b> [{ofi_res.ofi_label}]")
                lines.append(f"CVD: {ofi_res.cvd_label}")
                lines.append(f"Flow: {ofi_res.funding_div_label}")
                if ofi_res.caution_flags:
                    lines.append(f"⚠️ Caution: {', '.join(ofi_res.caution_flags)}")

            if not isinstance(basis_res, Exception) and basis_res:
                lines.append(
                    f"\nFutures/Spot Basis: {basis_res.basis_pct:+.3f}% "
                    f"[{basis_res.basis_label}]"
                )

            await update.message.reply_html("\n".join(lines))
        except Exception as exc:
            await update.message.reply_text(f"OFI analysis failed: {exc}")

    # ── /add /remove /news /block ──────────────────────────────────────────────

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
        await update.message.reply_html(
            f"✅ <b>{symbol}</b> added to scan list.\nNext scan এ include হবে।"
        )

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
        await update.message.reply_html(
            f"🗑️ <b>{symbol}</b> removed from dynamic scan list."
        )

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
            f"📰 <b>{symbol}</b> flagged as news-driven.\n"
            f"Volume filter relaxed to 1.5x for this coin."
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

    # ── /sl /tp1 /win /reset ──────────────────────────────────────────────────

    async def _cmd_sl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine

        engine._daily_sl_hits  += 1
        engine._consecutive_sl += 1

        lines = [
            "🔴 <b>SL hit recorded.</b>",
            f"Daily SL hits: {engine._daily_sl_hits}/{config.DAILY_MAX_SL_HITS}",
            f"Consecutive SL: {engine._consecutive_sl}/{config.CONSECUTIVE_SL_PAUSE}",
        ]

        if engine._consecutive_sl >= config.CONSECUTIVE_SL_PAUSE:
            engine._pause_until = datetime.now(IST) + timedelta(
                minutes=config.CONSECUTIVE_SL_PAUSE_MINUTES
            )
            pause_str = engine._pause_until.strftime("%H:%M IST")
            lines.append(
                f"\n⏸️ <b>PAUSE ACTIVE</b> — "
                f"{config.CONSECUTIVE_SL_PAUSE} consecutive SL."
            )
            lines.append(
                f"No signals until <b>{pause_str}</b>. Take a break."
            )
            engine._consecutive_sl = 0

        if engine._daily_sl_hits >= config.DAILY_MAX_SL_HITS:
            lines.append(
                f"\n🛑 <b>DAILY SL LIMIT REACHED</b> — No more signals today."
            )
            lines.append("Come back tomorrow with fresh eyes.")

        await update.message.reply_html("\n".join(lines))

    async def _cmd_tp1(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        prev = engine._consecutive_sl
        engine._consecutive_sl = max(0, engine._consecutive_sl - 1)
        await update.message.reply_html(
            f"🎯 <b>TP1 hit recorded!</b> Partial exit ✅\n"
            f"Consecutive SL: {prev} → {engine._consecutive_sl}\n\n"
            f"💡 Remaining position এর SL → entry তে move করো."
        )

    async def _cmd_win(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        prev = engine._consecutive_sl
        engine._consecutive_sl = 0
        await update.message.reply_html(
            f"✅ <b>Win recorded!</b>\n"
            f"Consecutive SL counter reset ({prev} → 0).\n"
            f"Daily signals sent: {engine._daily_signals_sent}"
        )

    async def _cmd_reset_daily(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return
        from core.engine import engine
        engine._daily_sl_hits      = 0
        engine._daily_signals_sent = 0
        engine._consecutive_sl     = 0
        engine._pause_until        = None
        await update.message.reply_html(
            "🔄 <b>Daily counters reset.</b>\n"
            "SL: 0 | Signals: 0 | Consecutive SL: 0 | Pause: OFF"
        )

    # ── /backtest ─────────────────────────────────────────────────────────────

    async def _cmd_backtest(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._is_authorised(update):
            return

        args      = ctx.args
        symbol    = "BTCUSDT"
        days      = 30
        direction = "LONG"

        if len(args) >= 1:
            symbol = args[0].upper()
            if not symbol.endswith("USDT"):
                symbol += "USDT"
        if len(args) >= 2:
            try:
                days = max(7, min(int(args[1]), 90))
            except ValueError:
                pass
        if len(args) >= 3 and args[2].upper() in ("LONG", "SHORT"):
            direction = args[2].upper()

        is_core = symbol in config.CORE_PAIRS

        await update.message.reply_html(
            f"⏳ Running <b>{days}-day</b> walk-forward backtest for "
            f"<b>{symbol}</b> {direction}...\n"
            f"30-60 seconds লাগবে।"
        )

        try:
            from backtest.backtest_engine import backtest_engine
            result = await backtest_engine.run(
                symbol=symbol,
                direction=direction,
                period_days=days,
                timeframe="15m",
                is_core_pair=is_core,
            )
            if result.total_signals == 0:
                await update.message.reply_html(
                    f"📊 Backtest: <b>{symbol}</b> {direction} {days}d\n"
                    f"No signals found. Try different symbol or longer period."
                )
            else:
                await update.message.reply_html(result.telegram_summary())
        except Exception as exc:
            logger.error(f"Backtest command failed: {exc}", exc_info=True)
            await update.message.reply_text(f"Backtest failed: {exc}")


telegram_bot = TelegramBot()
