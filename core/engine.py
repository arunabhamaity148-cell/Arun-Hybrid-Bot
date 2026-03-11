"""
core/engine.py — Main Orchestrator for Arunabha Hybrid Bot v1.0
Coordinates scanner, signal engine, Telegram notifications, and all data layers.
"""

import asyncio
import logging
import time
from datetime import datetime
import pytz

import config
from core.scanner import scanner
from core.signal_engine import signal_engine
from data.binance_client import binance, VolumeAnomalyWatcher
from data.coingecko_client import coingecko

logger = logging.getLogger(__name__)
IST = pytz.timezone(config.TIMEZONE)

_telegram = None
def _get_telegram():
    global _telegram
    if _telegram is None:
        from notification.telegram_bot import telegram_bot
        _telegram = telegram_bot
    return _telegram


class HybridEngine:

    def __init__(self):
        self._scan_count = 0
        self._signal_count_today = 0
        self._today_date = None
        self._signals_today: list[dict] = []
        self._fear_greed = {"value": 50, "value_classification": "Neutral"}
        self._btc_regime_cache = "UNKNOWN"
        self._volume_watcher = VolumeAnomalyWatcher(on_anomaly=self._on_volume_anomaly)
        self._anomaly_queue: asyncio.Queue = asyncio.Queue()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._last_signal_time: dict[str, datetime] = {}

    def _on_volume_anomaly(self, symbol: str, multiplier: float) -> None:
        scanner.on_volume_anomaly(symbol, multiplier)
        if self._event_loop is not None and not self._event_loop.is_closed():
            self._event_loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self._send_anomaly_alert(symbol, multiplier),
                    loop=self._event_loop,
                )
            )
        else:
            logger.warning(f"No event loop available for anomaly alert: {symbol}")

    async def _send_anomaly_alert(self, symbol: str, multiplier: float) -> None:
        try:
            tg = _get_telegram()
            msg = f"⚡ <b>Volume Anomaly: {symbol}</b> — {multiplier:.1f}x spike detected\n🔍 Added to scan list"
            await tg.send_message(msg)
        except Exception as exc:
            logger.warning(f"Anomaly alert send failed: {exc}")

    async def startup(self) -> None:
        logger.info("🚀 Arunabha Hybrid Bot v1.0 starting up...")
        self._event_loop = asyncio.get_running_loop()

        await scanner.refresh_market_caps()
        await scanner.refresh_trending()
        await scanner.refresh_gainers()

        fg = await coingecko.get_fear_greed()
        self._fear_greed = fg
        logger.info(f"Fear & Greed: {fg['value']} ({fg['value_classification']})")

        pairs = await scanner.get_active_pairs()
        self._volume_watcher.set_symbols(pairs)
        await self._volume_watcher.start()

        logger.info("✅ Engine startup complete")

        tg = _get_telegram()
        await tg.send_message(
            "🤖 <b>Arunabha Hybrid Bot v1.0</b> started!\n"
            f"📊 Monitoring {len(pairs)} pairs\n"
            f"😨 Fear & Greed: {fg['value']} ({fg['value_classification']})\n"
            "⚠️ Signal-only mode — NO auto trading"
        )

    async def run_hourly_tasks(self) -> None:
        logger.info("⏰ Running hourly tasks...")
        try:
            await scanner.refresh_market_caps()
            await scanner.refresh_trending()

            fg = await coingecko.get_fear_greed()
            self._fear_greed = fg
            logger.info(f"Fear & Greed refreshed: {fg['value']} ({fg['value_classification']})")

            new_futures = await binance.check_new_futures_listings()
            if new_futures:
                tg = _get_telegram()
                await tg.send_message(
                    f"🆕 <b>New Binance Futures Listings:</b>\n" +
                    "\n".join(f"• {s}" for s in new_futures[:10])
                )

            new_cg = await coingecko.get_new_listings()
            if new_cg:
                logger.info(f"New CoinGecko listings: {[c['symbol'] for c in new_cg[:5]]}")

        except Exception as exc:
            logger.error(f"Hourly tasks failed: {exc}", exc_info=True)

    async def run_scan(self) -> None:
        self._scan_count += 1
        scan_id = self._scan_count

        now_ist = datetime.now(IST)
        today = now_ist.date()
        if self._today_date != today:
            self._today_date = today
            self._signal_count_today = 0
            self._signals_today = []

        now_str = now_ist.strftime("%H:%M IST")

        await scanner.refresh_gainers()
        pairs = await scanner.get_active_pairs()
        self._volume_watcher.set_symbols(pairs)

        fg_val = self._fear_greed["value"]
        fg_class = self._fear_greed["value_classification"]
        caution = fg_val < config.FEAR_GREED_CAUTION_THRESHOLD  # kept for Telegram warning

        # Direction-aware Fear & Greed blocking (NEW)
        if config.FEAR_GREED_DIRECTION_FILTER:
            if fg_val <= config.FEAR_GREED_CAPITULATION_THRESHOLD:
                fg_long_blocked = False
                fg_short_blocked = False
                fg_state = f"CAPITULATION ({fg_val}) — contrarian LONG+SHORT allowed"
            elif fg_val < config.FEAR_GREED_LONG_MIN:
                fg_long_blocked = True
                fg_short_blocked = False
                fg_state = f"EXTREME FEAR ({fg_val}) — LONG blocked, SHORT only"
            elif fg_val >= config.FEAR_GREED_EUPHORIA_THRESHOLD:
                fg_long_blocked = False
                fg_short_blocked = False
                fg_state = f"EUPHORIA ({fg_val}) — contrarian LONG+SHORT allowed"
            elif fg_val > config.FEAR_GREED_SHORT_MAX:
                fg_long_blocked = False
                fg_short_blocked = True
                fg_state = f"EXTREME GREED ({fg_val}) — SHORT blocked, LONG only"
            else:
                fg_long_blocked = False
                fg_short_blocked = False
                fg_state = f"NORMAL ({fg_val})"
        else:
            fg_long_blocked = False
            fg_short_blocked = False
            fg_state = f"{fg_val} ({fg_class})"

        core_syms = " ".join(p.replace("USDT", "") for p in config.CORE_PAIRS)
        gainer_syms = " ".join(
            f"{g['symbol'].replace('USDT','')}(+{g['change_pct']:.1f}%)"
            for g in scanner._gainer_pairs
        )
        trending_syms = " ".join(p.replace("USDT", "") for p in scanner._trending_pairs)

        separator = "═" * 44
        print(f"\n{separator}")
        print(f"⏰ SCAN #{scan_id} | {now_str} | 5min cycle")
        print(separator)

        from filters.btc_regime import check_btc_regime
        _, btc_msg = await check_btc_regime("LONG")
        regime_short = "BEAR" if "BEAR" in btc_msg else ("BULL" if "BULL" in btc_msg else "NEUTRAL")
        adx_part = btc_msg.split("(")[1].split(")")[0] if "(" in btc_msg else ""
        print(f"📊 BTC Regime: {regime_short} ({adx_part})")
        self._btc_regime_cache = regime_short

        caution_str = " — ⚠️ CAUTION MODE" if caution else ""
        print(f"😨 Fear & Greed: {fg_state}{caution_str}")

        pair_count = len(pairs)
        print(f"📋 Active Pairs ({pair_count}): {core_syms}", end="")
        if gainer_syms:
            print(f" | {gainer_syms}", end="")
        if trending_syms:
            print(f" | Trending: {trending_syms}", end="")
        print()
        print("─" * 44)

        if config.SESSION_FILTER_ENABLED:
            ist_hour = now_ist.hour
            if config.DEAD_ZONE_START_HOUR <= ist_hour < config.DEAD_ZONE_END_HOUR:
                print(f"\n🌙 DEAD ZONE ({ist_hour:02d}:xx IST) — no signals until {config.DEAD_ZONE_END_HOUR:02d}:00 IST")
                dead_zone = True
            else:
                dead_zone = False
        else:
            dead_zone = False

        signals_this_scan: list = []

        for symbol in pairs:
            print(f"\n🔍 {symbol}:")
            try:
                for direction in ("LONG", "SHORT"):
                    # Fear & Greed direction block (NEW)
                    if direction == "LONG" and fg_long_blocked:
                        print(f"  ⛔ F&G BLOCK: LONG skipped — {fg_state}")
                        continue
                    if direction == "SHORT" and fg_short_blocked:
                        print(f"  ⛔ F&G BLOCK: SHORT skipped — {fg_state}")
                        continue

                    news_mode = scanner.is_news_flagged(symbol)
                    is_gainer = scanner.get_gainer_info(symbol) is not None
                    is_trending = scanner.get_trending_rank(symbol) is not None
                    result = await signal_engine.evaluate(
                        symbol, direction, news_mode,
                        is_gainer=is_gainer,
                        is_trending=is_trending,
                    )

                    for line in result.filter_log_lines():
                        print(line)

                    if result.has_signal:
                        cooldown_key = f"{symbol}:{direction}"
                        last_sig = self._last_signal_time.get(cooldown_key)
                        cooldown_mins = config.SIGNAL_COOLDOWN_MINUTES
                        if last_sig is not None:
                            elapsed = (now_ist - last_sig).total_seconds() / 60
                            if elapsed < cooldown_mins:
                                remaining = cooldown_mins - elapsed
                                print(
                                    f"  🕐 COOLDOWN: {symbol} {direction} — "
                                    f"last signal {elapsed:.0f}min ago, "
                                    f"wait {remaining:.0f}min more"
                                )
                                break

                        if dead_zone:
                            print(f"  🌙 DEAD ZONE: Signal suppressed (IST {now_ist.hour:02d}:xx)")
                            break

                        self._last_signal_time[cooldown_key] = now_ist
                        self._signal_count_today += 1
                        sig_num = self._signal_count_today
                        signal_data = {
                            "symbol": symbol,
                            "direction": direction,
                            "entry": result.entry,
                            "sl": result.sl,
                            "tp1": result.tp1,
                            "tp2": result.tp2,
                            "rr": result.rr,
                            "scan": scan_id,
                            "time": now_str,
                            "num": sig_num,
                        }
                        signals_this_scan.append(signal_data)
                        self._signals_today.append(signal_data)

                        await self._send_signal_telegram(
                            result, scanner.get_gainer_info(symbol),
                            scanner.get_trending_rank(symbol),
                            scanner.is_anomaly(symbol),
                            fg_val, fg_class, regime_short, adx_part,
                            now_str, sig_num, caution,
                        )
                        break

            except Exception as exc:
                logger.error(f"Scan error for {symbol}: {exc}", exc_info=True)
                print(f"  ⚠️ Error scanning {symbol}: {exc}")

            print("─" * 44)

        for sym in scanner._anomaly_pairs:
            print(f"⚡ VOLUME ANOMALY: {sym.replace('USDT','')} — spike detected")

        print(separator)
        logger.info(
            f"Scan #{scan_id} complete — {pair_count} pairs | "
            f"{len(signals_this_scan)} new signals | "
            f"{self._signal_count_today} today"
        )

    async def _send_signal_telegram(
        self, result, gainer_info, trending_rank, is_anomaly,
        fg_val, fg_class, btc_regime, adx_part, now_str, sig_num, caution,
    ) -> None:
        try:
            direction_emoji = "🟢" if result.direction == "LONG" else "🔴"
            now_ist = datetime.now(IST)
            hour = now_ist.hour
            if 8 <= hour < 12:
                session = "Asia Open"
            elif 12 <= hour < 16:
                session = "London Open"
            elif 16 <= hour < 20:
                session = "NY Open"
            else:
                session = "Off-Hours"

            why_lines = []
            if gainer_info:
                why_lines.append(f"• Volume spike: {gainer_info.get('vol_multiplier', '?')}x")
                why_lines.append(f"• 24h Gain: +{gainer_info['change_pct']:.1f}%")
            if trending_rank:
                why_lines.append(f"• CoinGecko Trending: #{trending_rank}")
            if is_anomaly:
                why_lines.append("• Catalyst: Volume anomaly detected")
            why_section = "\n".join(why_lines) if why_lines else "• Part of core watch list"

            caution_line = "\n⚠️ <b>FEAR & GREED EXTREME — reduce size!</b>" if caution else ""

            setup_desc = "Liquidity Grab + CHoCH + FVG"
            fvg_line = f"📦 FVG Zone: <code>{result.fvg_low:.8g}</code> — <code>{result.fvg_high:.8g}</code>\n"
            entry_label = "FVG touch"

            # Multi-TF confluence badge
            confluence_badge = ""
            if getattr(result, "multitf_confluence", False):
                confluence_badge = " ✨ <b>[MULTI-TF CONFLUENCE]</b>"
                setup_desc = "Liq Grab + CHoCH + FVG (15m+1h aligned)"

            if getattr(result, "fvg_optional_miss", False):
                setup_desc = "Liquidity Grab + CHoCH (no FVG — CHoCH entry)"
                fvg_line = "📦 FVG: Not found — entering at CHoCH level\n"
                entry_label = "CHoCH level"

            choch_val = f"{result.choch_level:.8g}" if result.choch_level else "N/A"

            msg = (
                f"🔥 <b>ARUNABHA HYBRID SIGNAL</b>{confluence_badge}\n\n"
                f"📌 Pair: <b>{result.symbol}</b>\n"
                f"📊 Setup: {setup_desc}\n"
                f"{direction_emoji} Direction: <b>{result.direction}</b>\n\n"
                f"💧 Grab Level: <code>{result.grab_level:.8g}</code>\n"
                f"✅ CHoCH: Confirmed at <code>{choch_val}</code>\n"
                f"{fvg_line}\n"
                f"💵 Entry: <code>{result.entry:.8g}</code> ({entry_label})\n"
                f"🛑 SL: <code>{result.sl:.8g}</code> (below grab — {result.sl_pct:.1f}%)\n"
                f"🎯 TP1: <code>{result.tp1:.8g}</code> (1.5R — exit 50% manually)\n"
                f"🎯 TP2: <code>{result.tp2:.8g}</code> (3.0R — exit remaining 50% manually)\n"
                f"📐 RR: {result.rr:.2f}:1\n\n"
                f"📈 <b>Why This Coin:</b>\n{why_section}\n\n"
                f"📊 <b>Market Context:</b>\n"
                f"• BTC: {btc_regime} ({adx_part})\n"
                f"• Fear & Greed: {fg_val} ({fg_class}){caution_line}\n"
                f"• Session: {session}\n\n"
                f"⚠️ <b>EXECUTE MANUALLY ON DELTA EXCHANGE</b>\n"
                f"⏰ {now_str} | Signal #{sig_num} today"
            )

            tg = _get_telegram()
            await tg.send_message(msg)

        except Exception as exc:
            logger.error(f"Signal Telegram send failed: {exc}", exc_info=True)

    def get_status_dict(self) -> dict:
        return {
            "scan_count": self._scan_count,
            "signals_today": self._signal_count_today,
            "btc_regime": self._btc_regime_cache,
            "fear_greed": self._fear_greed,
            "scanner_status": scanner.get_status(),
        }

    def get_signals_today(self) -> list[dict]:
        return list(self._signals_today)


engine = HybridEngine()
