"""
core/engine.py — Main Orchestrator for Arunabha Hybrid Bot v1.0
Priority 1+2+3+4 Update:
  - get_intel() call added after signal generate হলে
  - Intel data → AI rater prompt এ যায় (real CoinGecko+CoinDesk data)
  - Intel data → Telegram signal message এ দেখায়
  - Signal score → Telegram এ দেখায়
  - Delta price reference added
""" 
import asyncio
import logging
import time
from datetime import datetime
import pytz

import config
from core.scanner      import scanner
from core.signal_engine import signal_engine
from data.binance_client import binance, VolumeAnomalyWatcher
from data.coingecko_client import coingecko

logger = logging.getLogger(__name__)
IST    = pytz.timezone(config.TIMEZONE)

_telegram = None
def _get_telegram():
    global _telegram
    if _telegram is None:
        from notification.telegram_bot import telegram_bot
        _telegram = telegram_bot
    return _telegram


class HybridEngine:

    def __init__(self):
        self._scan_count           = 0
        self._signal_count_today   = 0
        self._today_date           = None
        self._signals_today: list  = []
        self._fear_greed           = {"value": 50, "value_classification": "Neutral"}
        self._btc_regime_cache     = "UNKNOWN"
        self._volume_watcher       = VolumeAnomalyWatcher(on_anomaly=self._on_volume_anomaly)
        self._anomaly_queue        = asyncio.Queue()
        self._event_loop           = None
        self._last_signal_time     = {}

        # Daily Protection
        self._daily_sl_hits        = 0
        self._daily_signals_sent   = 0
        self._consecutive_sl       = 0
        self._pause_until          = None

    def _on_volume_anomaly(self, symbol: str, multiplier: float) -> None:
        scanner.on_volume_anomaly(symbol, multiplier)
        if self._event_loop is not None and not self._event_loop.is_closed():
            self._event_loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self._send_anomaly_alert(symbol, multiplier),
                    loop=self._event_loop,
                )
            )

    async def _send_anomaly_alert(self, symbol: str, multiplier: float) -> None:
        try:
            tg  = _get_telegram()
            msg = (
                f"⚡ <b>Volume Anomaly: {symbol}</b> — {multiplier:.1f}x spike\n"
                f"🔍 Added to scan list"
            )
            await tg.send_message(msg)
        except Exception as exc:
            logger.warning(f"Anomaly alert failed: {exc}")

    async def startup(self) -> None:
        logger.info("🚀 Arunabha Hybrid Bot v1.0 starting...")
        self._event_loop = asyncio.get_running_loop()

        await scanner.refresh_market_caps()
        await scanner.refresh_trending()
        await scanner.refresh_gainers()

        fg = await coingecko.get_fear_greed()
        self._fear_greed = fg

        pairs = await scanner.get_active_pairs()
        self._volume_watcher.set_symbols(pairs)
        await self._volume_watcher.start()

        logger.info("✅ Engine startup complete")

        tg = _get_telegram()
        await tg.send_message(
            "🤖 <b>Arunabha Hybrid Bot v1.0</b> started!\n"
            f"📊 Monitoring {len(pairs)} pairs\n"
            f"😨 Fear & Greed: {fg['value']} ({fg['value_classification']})\n"
            "⚠️ Signal-only — NO auto trading"
        )

    async def run_hourly_tasks(self) -> None:
        logger.info("⏰ Hourly tasks running...")
        try:
            await scanner.refresh_market_caps()
            await scanner.refresh_trending()

            fg = await coingecko.get_fear_greed()
            self._fear_greed = fg

            new_futures = await binance.check_new_futures_listings()
            if new_futures:
                tg = _get_telegram()
                await tg.send_message(
                    "🆕 <b>New Binance Futures Listings:</b>\n" +
                    "\n".join(f"• {s}" for s in new_futures[:10])
                )
        except Exception as exc:
            logger.error(f"Hourly tasks failed: {exc}", exc_info=True)

    async def run_scan(self) -> None:
        self._scan_count += 1
        scan_id = self._scan_count

        now_ist = datetime.now(IST)
        today   = now_ist.date()

        if self._today_date != today:
            self._today_date         = today
            self._signal_count_today = 0
            self._signals_today      = []
            self._daily_sl_hits      = 0
            self._daily_signals_sent = 0
            self._consecutive_sl     = 0
            self._pause_until        = None

        now_str = now_ist.strftime("%H:%M IST")

        await scanner.refresh_gainers()
        pairs = await scanner.get_active_pairs()
        self._volume_watcher.set_symbols(pairs)

        fg_val   = self._fear_greed["value"]
        fg_class = self._fear_greed["value_classification"]
        caution  = fg_val < config.FEAR_GREED_CAUTION_THRESHOLD

        # Fear & Greed direction blocking
        if config.FEAR_GREED_DIRECTION_FILTER:
            if fg_val <= config.FEAR_GREED_CAPITULATION_THRESHOLD:
                fg_long_blocked = fg_short_blocked = False
                fg_state = f"CAPITULATION ({fg_val}) — contrarian both allowed"
            elif fg_val < config.FEAR_GREED_LONG_MIN:
                fg_long_blocked  = True
                fg_short_blocked = False
                fg_state = f"EXTREME FEAR ({fg_val}) — LONG blocked"
            elif fg_val >= config.FEAR_GREED_EUPHORIA_THRESHOLD:
                fg_long_blocked = fg_short_blocked = False
                fg_state = f"EUPHORIA ({fg_val}) — contrarian both allowed"
            elif fg_val > config.FEAR_GREED_SHORT_MAX:
                fg_long_blocked  = False
                fg_short_blocked = True
                fg_state = f"EXTREME GREED ({fg_val}) — SHORT blocked"
            else:
                fg_long_blocked = fg_short_blocked = False
                fg_state = f"NORMAL ({fg_val})"
        else:
            fg_long_blocked = fg_short_blocked = False
            fg_state = f"{fg_val} ({fg_class})"

        from filters.btc_regime import check_btc_regime
        _, btc_msg = await check_btc_regime("LONG")
        regime_short = (
            "BEAR"    if "BEAR"    in btc_msg else
            "BULL"    if "BULL"    in btc_msg else
            "NEUTRAL"
        )
        adx_part = btc_msg.split("(")[1].split(")")[0] if "(" in btc_msg else ""
        self._btc_regime_cache = regime_short

        # Console header
        sep = "═" * 44
        print(f"\n{sep}")
        print(f"⏰ SCAN #{scan_id} | {now_str}")
        print(f"📊 BTC: {regime_short} ({adx_part})")
        print(f"😨 F&G: {fg_state}")
        print(f"📋 Pairs: {len(pairs)}")
        print("─" * 44)

        # Session dead zone
        dead_zone = (
            config.SESSION_FILTER_ENABLED
            and config.DEAD_ZONE_START_HOUR <= now_ist.hour < config.DEAD_ZONE_END_HOUR
        )
        if dead_zone:
            print(f"🌙 DEAD ZONE ({now_ist.hour:02d}:xx IST)")

        signals_this_scan = []

        for symbol in pairs:
            print(f"\n🔍 {symbol}:")
            try:
                for direction in ("LONG", "SHORT"):
                    if direction == "LONG"  and fg_long_blocked:
                        print(f"  ⛔ F&G: LONG blocked — {fg_state}")
                        continue
                    if direction == "SHORT" and fg_short_blocked:
                        print(f"  ⛔ F&G: SHORT blocked — {fg_state}")
                        continue

                    news_mode   = scanner.is_news_flagged(symbol)
                    is_gainer   = scanner.get_gainer_info(symbol)   is not None
                    is_trending = scanner.get_trending_rank(symbol)  is not None

                    result = await signal_engine.evaluate(
                        symbol, direction, news_mode,
                        is_gainer=is_gainer, is_trending=is_trending,
                    )

                    for line in result.filter_log_lines():
                        print(line)

                    if not result.has_signal:
                        continue

                    # ── Daily Protection ──────────────────────────────────
                    if self._pause_until and now_ist < self._pause_until:
                        rem = int((self._pause_until - now_ist).total_seconds() // 60)
                        print(f"  ⏸️  PAUSE: {rem}min left")
                        continue

                    if self._daily_signals_sent >= config.DAILY_MAX_SIGNALS:
                        print(f"  🛑 DAILY LIMIT reached")
                        continue

                    if self._daily_sl_hits >= config.DAILY_MAX_SL_HITS:
                        print(f"  🛑 DAILY SL LIMIT reached")
                        continue

                    cooldown_key = f"{symbol}:{direction}"
                    last_sig     = self._last_signal_time.get(cooldown_key)
                    if last_sig:
                        elapsed = (now_ist - last_sig).total_seconds() / 60
                        if elapsed < config.SIGNAL_COOLDOWN_MINUTES:
                            print(f"  🕐 COOLDOWN: {config.SIGNAL_COOLDOWN_MINUTES - elapsed:.0f}min left")
                            break

                    if dead_zone:
                        print(f"  🌙 DEAD ZONE — suppressed")
                        break

                    # ── Fetch Market Intel (Priority 1+2+3) ───────────────
                    # Signal pass হয়েছে — এখন 3 app থেকে deep intel নাও
                    intel = None
                    try:
                        from data.market_intel import get_intel
                        intel = await get_intel(symbol)
                        print(
                            f"  🔬 Intel: {intel.overall_sentiment} "
                            f"({intel.sentiment_score}/100) | "
                            f"CG: {intel.cg_bull_pct:.0f}%bull"
                        )
                    except Exception as exc:
                        logger.warning(f"Intel fetch failed for {symbol}: {exc}")

                    # ── AI Rating (with OHLCV + Intel) ────────────────────
                    from core.ai_rater import rate_signal, rating_emoji, should_suppress

                    session_label = (
                        "London Open" if 8  <= now_ist.hour < 11  else
                        "NY Open"     if 19 <= now_ist.hour < 22  else
                        "Asia Open"   if 6  <= now_ist.hour < 9   else
                        "Regular"
                    )

                    ai_rating, ai_reason = await rate_signal(
                        symbol=symbol,
                        direction=direction,
                        rr=result.rr or 0,
                        btc_regime=regime_short,
                        fg_val=fg_val,
                        fg_class=fg_class,
                        session=session_label,
                        multitf_confluence=result.multitf_confluence,
                        pullback_pct=None,
                        pump_age_hr=None,
                        is_gainer=is_gainer,
                        is_trending=is_trending,
                        sl_pct=result.sl_pct or 0,
                        funding_rate_pct=result.funding_rate_pct,
                        funding_label=result.funding_label,
                        entry=result.entry,
                        sl=result.sl,
                        tp1=result.tp1,
                        tp2=result.tp2,
                        grab_level=result.grab_level,
                        choch_level=result.choch_level,
                        intel=intel,
                    )
                    print(
                        f"  🤖 AI: {ai_rating} {rating_emoji(ai_rating)} — {ai_reason}"
                    )

                    if should_suppress(ai_rating):
                        print("  🚫 AI SUPPRESS: C-rated blocked")
                        break

                    # ── Intel-based score adjustment ──────────────────────
                    final_score = result.signal_score
                    if intel:
                        if intel.sentiment_score >= 70:
                            final_score = min(100, final_score + 5)
                        elif intel.sentiment_score <= 30:
                            final_score = max(0, final_score - 5)
                        result.signal_score = final_score

                    self._last_signal_time[cooldown_key] = now_ist
                    self._signal_count_today  += 1
                    self._daily_signals_sent  += 1
                    sig_num = self._signal_count_today

                    signal_data = {
                        "symbol":    symbol,
                        "direction": direction,
                        "entry":     result.entry,
                        "sl":        result.sl,
                        "tp1":       result.tp1,
                        "tp2":       result.tp2,
                        "rr":        result.rr,
                        "score":     result.signal_score,
                        "ai_rating": ai_rating,
                        "ai_reason": ai_reason,
                        "scan":      scan_id,
                        "time":      now_str,
                        "num":       sig_num,
                    }
                    signals_this_scan.append(signal_data)
                    self._signals_today.append(signal_data)

                    await self._send_signal_telegram(
                        result=result,
                        gainer_info=scanner.get_gainer_info(symbol),
                        trending_rank=scanner.get_trending_rank(symbol),
                        is_anomaly=scanner.is_anomaly(symbol),
                        fg_val=fg_val,
                        fg_class=fg_class,
                        btc_regime=regime_short,
                        adx_part=adx_part,
                        now_str=now_str,
                        sig_num=sig_num,
                        caution=caution,
                        ai_rating=ai_rating,
                        ai_reason=ai_reason,
                        intel=intel,
                    )
                    break

            except Exception as exc:
                logger.error(f"Scan error {symbol}: {exc}", exc_info=True)
                print(f"  ⚠️ Error: {exc}")

            print("─" * 44)

        print(sep)
        logger.info(
            f"Scan #{scan_id} done — {len(pairs)} pairs | "
            f"{len(signals_this_scan)} new signals | "
            f"{self._signal_count_today} today"
        )

    async def _send_signal_telegram(
        self,
        result,
        gainer_info,
        trending_rank,
        is_anomaly,
        fg_val, fg_class,
        btc_regime, adx_part,
        now_str, sig_num,
        caution,
        ai_rating: str = "N/A",
        ai_reason: str = "",
        intel=None,
    ) -> None:
        try:
            from core.ai_rater import rating_emoji
            direction_emoji = "🟢" if result.direction == "LONG" else "🔴"
            now_ist = datetime.now(IST)
            hour    = now_ist.hour

            if   8  <= hour < 12: session = "Asia Open"
            elif 12 <= hour < 16: session = "London Open"
            elif 16 <= hour < 20: session = "NY Open"
            else:                  session = "Off-Hours"

            # Why this coin section
            why_lines = []
            if gainer_info:
                why_lines.append(f"• Volume spike: {gainer_info.get('vol_multiplier','?')}x")
                why_lines.append(f"• 24h Gain: +{gainer_info['change_pct']:.1f}%")
            if trending_rank:
                why_lines.append(f"• CoinGecko Trending: #{trending_rank}")
            if is_anomaly:
                why_lines.append("• Catalyst: Volume anomaly")
            if not why_lines:
                why_lines.append("• Part of core watch list")
            why_section = "\n".join(why_lines)

            # Setup description
            if result.multitf_confluence:
                setup_desc    = "Liq Grab + CHoCH + FVG (15m+1h aligned)"
                confluence_badge = " ✨ <b>[MULTI-TF]</b>"
            else:
                setup_desc    = "Liquidity Grab + CHoCH + FVG"
                confluence_badge = ""

            fvg_line    = f"📦 FVG Zone: <code>{result.fvg_low:.8g}</code> — <code>{result.fvg_high:.8g}</code>\n"
            entry_label = "FVG touch"

            if result.fvg_optional_miss:
                setup_desc  = "Liq Grab + CHoCH (no FVG — CHoCH entry)"
                fvg_line    = "📦 FVG: Not found — CHoCH entry\n"
                entry_label = "CHoCH level"

            choch_val = f"{result.choch_level:.8g}" if result.choch_level else "N/A"
            caution_line = "\n⚠️ <b>FEAR & GREED EXTREME — reduce size!</b>" if caution else ""

            # Signal Score bar
            score      = result.signal_score
            score_bar  = "🟩" * (score // 20) + "⬜" * (5 - score // 20)
            if score >= 80:
                score_label = "🔥 HIGH CONVICTION"
            elif score >= 65:
                score_label = "✅ GOOD SETUP"
            elif score >= 50:
                score_label = "⚠️ MODERATE"
            else:
                score_label = "❗ WEAK — consider skipping"

            breakdown = result.score_breakdown
            score_detail = (
                f"RR:{breakdown.get('RR',0)} "
                f"TF:{breakdown.get('MultiTF',0)} "
                f"Fund:{breakdown.get('Funding',0)} "
                f"F&G:{breakdown.get('FG',0)} "
                f"Sess:{breakdown.get('Session',0)} "
                f"Warn:{breakdown.get('WarnFilters',0)}"
            )

            # Intel section (CoinGecko + CoinDesk + CMC)
            intel_section = intel.as_telegram_section() if intel else ""

            msg = (
                f"🔥 <b>ARUNABHA HYBRID SIGNAL</b>{confluence_badge}\n\n"
                f"📌 Pair: <b>{result.symbol}</b>\n"
                f"📊 Setup: {setup_desc}\n"
                f"{direction_emoji} Direction: <b>{result.direction}</b>\n\n"
                f"💧 Grab Level: <code>{result.grab_level:.8g}</code>\n"
                f"✅ CHoCH: <code>{choch_val}</code>\n"
                f"{fvg_line}\n"
                f"💵 Entry: <code>{result.entry:.8g}</code> ({entry_label})\n"
                f"🛑 SL: <code>{result.sl:.8g}</code> ({result.sl_pct:.1f}%)\n"
                f"🎯 TP1: <code>{result.tp1:.8g}</code> (1.5R — 50% exit)\n"
                f"🎯 TP2: <code>{result.tp2:.8g}</code> (3.0R — 50% exit)\n"
                f"📐 RR: {result.rr:.2f}:1\n\n"
                f"🎯 <b>Signal Score: {score}/100</b> — {score_label}\n"
                f"{score_bar} [{score_detail}]\n\n"
                f"📈 <b>Why This Coin:</b>\n{why_section}\n"
                f"{intel_section}\n\n"
                f"📊 <b>Market Context:</b>\n"
                f"• BTC: {btc_regime} ({adx_part})\n"
                f"• Fear & Greed: {fg_val} ({fg_class}){caution_line}\n"
                f"• Funding: {result.funding_rate_pct:+.3f}% [{result.funding_label}]\n"
                f"• Session: {session}\n\n"
                f"⚠️ <b>EXECUTE MANUALLY ON DELTA EXCHANGE</b>\n"
                f"⏰ {now_str} | Signal #{sig_num} today"
            )

            if ai_rating != "N/A":
                msg += (
                    f"\n\n🤖 <b>AI Rating: {ai_rating}</b> "
                    f"{rating_emoji(ai_rating)} — {ai_reason}"
                )

            tg = _get_telegram()
            await tg.send_message(msg)

        except Exception as exc:
            logger.error(f"Signal TG send failed: {exc}", exc_info=True)

    def get_status_dict(self) -> dict:
        return {
            "scan_count":    self._scan_count,
            "signals_today": self._signal_count_today,
            "btc_regime":    self._btc_regime_cache,
            "fear_greed":    self._fear_greed,
            "scanner_status":scanner.get_status(),
        }

    def get_signals_today(self) -> list[dict]:
        return list(self._signals_today)


engine = HybridEngine()