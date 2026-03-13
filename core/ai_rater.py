"""
core/ai_rater.py — Signal Quality Rater (ChatGPT removed — Fix 2)

Option A (default): Rule-based smart rater — FREE, zero API
Option B (optional): Ollama local LLM — FREE, needs ollama.ai install
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

import aiohttp
import pytz
import config

if TYPE_CHECKING:
    from data.market_intel import IntelReport

logger = logging.getLogger(__name__)
IST    = pytz.timezone("Asia/Kolkata")


async def _get_ohlcv(symbol: str) -> list[dict]:
    try:
        if getattr(config, "USE_DELTA_DATA", False):
            from data.delta_client import delta
            df = await delta.get_klines(symbol, "15m", limit=15)
            if df is not None and not df.empty:
                return df.tail(12).to_dict("records")
    except Exception:
        pass
    try:
        from data.binance_client import binance
        df = await binance.get_klines(symbol, "15m", limit=15)
        if df is not None and not df.empty:
            return df.tail(12).to_dict("records")
    except Exception:
        pass
    return []


async def _get_delta_price(symbol: str) -> Optional[float]:
    try:
        if not getattr(config, "USE_DELTA_DATA", False):
            return None
        from data.delta_client import delta
        return await delta.get_mark_price(symbol)
    except Exception:
        return None


def _analyze_candles(candles: list[dict], direction: str) -> tuple[int, list[str]]:
    if not candles or len(candles) < 5:
        return 10, ["insufficient data"]

    closes  = [float(c["close"])  for c in candles]
    opens   = [float(c["open"])   for c in candles]
    highs   = [float(c["high"])   for c in candles]
    lows    = [float(c["low"])    for c in candles]
    volumes = [float(c["volume"]) for c in candles]

    score = 0
    obs   = []

    last_bull = closes[-1] > opens[-1]
    if (direction == "LONG" and last_bull) or (direction == "SHORT" and not last_bull):
        score += 5
        obs.append("last candle aligned")
    else:
        obs.append("last candle against direction")

    avg_vol  = sum(volumes[:-2]) / max(len(volumes)-2, 1)
    last_vol = volumes[-2]
    if avg_vol > 0:
        vr = last_vol / avg_vol
        if vr >= 2.5:   score += 10; obs.append(f"strong volume {vr:.1f}x")
        elif vr >= 1.5: score += 6;  obs.append(f"good volume {vr:.1f}x")
        else:                         obs.append(f"weak volume {vr:.1f}x")

    last3_bull = sum(1 for i in range(-4,-1) if closes[i] > opens[i])
    if (direction == "LONG" and last3_bull >= 2) or (direction == "SHORT" and last3_bull <= 1):
        score += 5; obs.append("momentum aligned")
    else:
        obs.append("mixed momentum")

    last_body  = abs(closes[-2] - opens[-2])
    last_range = highs[-2] - lows[-2]
    body_ratio = last_body / last_range if last_range > 0 else 0
    if body_ratio >= 0.6: score += 5; obs.append(f"strong body {body_ratio:.0%}")
    else:                              obs.append(f"weak body {body_ratio:.0%}")

    avg_body  = sum(abs(closes[i]-opens[i]) for i in range(-5,-1)) / 4
    avg_range = sum(highs[i]-lows[i] for i in range(-5,-1)) / 4
    if avg_range > 0 and avg_body/avg_range >= 0.5:
        score += 5; obs.append("clean structure")
    else:
        obs.append("choppy structure")

    return min(30, score), obs[:3]


def _rule_based_rate(rr, btc_regime, fg_val, session, multitf_confluence,
                     sl_pct, funding_label, candle_score, candle_obs,
                     intel, direction, price_discrepancy=0.0):
    score   = 0
    reasons = []

    if rr >= 4.0:   score += 25; reasons.append(f"excellent RR {rr:.1f}")
    elif rr >= 3.0: score += 20; reasons.append(f"good RR {rr:.1f}")
    elif rr >= 2.5: score += 14
    else:           score += 5;  reasons.append(f"low RR {rr:.1f}")

    if multitf_confluence: score += 15; reasons.append("multi-TF confluence")
    else:                  score += 4

    score += candle_score
    if candle_obs: reasons.append(candle_obs[0])

    if "NY" in session or "London" in session: score += 10; reasons.append(session)
    elif "Asia" in session:                    score += 5
    else:                                      score += 2

    if 35 <= fg_val <= 70:   score += 8
    elif 20 <= fg_val <= 80: score += 5
    else:                     score += 1; reasons.append(f"extreme F&G {fg_val}")

    if funding_label == "NEUTRAL":    score += 7
    elif "CAUTION" in funding_label:  score += 4
    elif funding_label == "DISABLED": score += 5
    else:                              score += 1; reasons.append(f"crowded {funding_label}")

    if intel:
        if (direction=="LONG" and intel.sentiment_score>=60) or \
           (direction=="SHORT" and intel.sentiment_score<=40):
            score += 5; reasons.append(f"intel aligned {intel.sentiment_score}/100")
        elif (direction=="LONG" and intel.sentiment_score<=35) or \
             (direction=="SHORT" and intel.sentiment_score>=65):
            score -= 5; reasons.append(f"intel against {intel.sentiment_score}/100")

    if price_discrepancy > 1.0:   score -= 8; reasons.append(f"price gap {price_discrepancy:.1f}%")
    elif price_discrepancy > 0.5: score -= 3

    score = max(0, min(100, score))

    if score >= 80:   rating = "A+"
    elif score >= 65: rating = "A"
    elif score >= 48: rating = "B"
    else:             rating = "C"

    reason = " | ".join(reasons[:3]) if reasons else "standard setup"
    return rating, reason


async def _ollama_rate(prompt: str) -> tuple[str, str]:
    url   = getattr(config, "OLLAMA_URL",   "http://localhost:11434")
    model = getattr(config, "OLLAMA_MODEL", "mistral")
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as sess:
            async with sess.post(f"{url}/api/generate",
                                 json={"model": model, "prompt": prompt, "stream": False}) as resp:
                if resp.status != 200: return "N/A", "Ollama unavailable"
                data   = await resp.json()
                text   = data.get("response", "").strip()
                rating = "N/A"; reason = "no reason"
                for line in text.split("\n"):
                    if line.startswith("RATING:"):
                        raw = line.replace("RATING:","").strip().upper()
                        if raw in ("A+","A","B","C"): rating = raw
                    elif line.startswith("REASON:"):
                        reason = line.replace("REASON:","").strip()
                return rating, reason
    except Exception as exc:
        logger.debug(f"Ollama error: {exc}")
        return "N/A", "Ollama unavailable"


async def rate_signal(symbol, direction, rr, btc_regime, fg_val, fg_class,
                      session, multitf_confluence, pullback_pct, pump_age_hr,
                      is_gainer, is_trending, sl_pct, funding_rate_pct=0.0,
                      funding_label="N/A", entry=None, sl=None, tp1=None,
                      tp2=None, grab_level=None, choch_level=None, intel=None):

    if not getattr(config, "SIGNAL_AI_RATING_ENABLED", True):
        return "N/A", "rating disabled"

    candles, delta_price = await asyncio.gather(_get_ohlcv(symbol), _get_delta_price(symbol))

    price_discrepancy = 0.0
    if delta_price and entry:
        price_discrepancy = abs(delta_price - entry) / entry * 100

    candle_score, candle_obs = _analyze_candles(candles, direction)

    ist_hour = datetime.now(IST).hour
    if 16 <= ist_hour <= 21:   session = "NY Open"
    elif 13 <= ist_hour <= 16: session = "London Open"
    elif 9 <= ist_hour <= 13:  session = "Asia Open"
    else:                       session = "Off-Hours"

    # Build shared prompt strings (used by both OpenAI and Ollama)
    ohlcv_str = "\n".join(
        f"{'🟢' if float(c['close'])>=float(c['open']) else '🔴'} "
        f"O:{float(c['open']):.4g} H:{float(c['high']):.4g} "
        f"L:{float(c['low']):.4g} C:{float(c['close']):.4g} "
        f"Vol:{float(c['volume']):.0f} Body:{abs(float(c['close'])-float(c['open']))/float(c['open'])*100:.2f}%"
        for c in candles
    ) if candles else "no candle data"
    intel_str    = intel.as_ai_context() if intel else "market intel: unavailable"
    levels_str   = (f"Entry:{entry:.6g} SL:{sl:.6g} TP1:{tp1:.6g} TP2:{tp2:.6g}"
                    if entry and sl and tp1 and tp2 else "levels: N/A")
    disc_str     = (f"\n⚠️ Price gap: Delta={delta_price:.4g} vs Entry={entry:.4g} "
                    f"({price_discrepancy:.2f}%)" if price_discrepancy > 0.5 else "")

    full_prompt = f"""You are a strict crypto futures signal evaluator. Rate this signal A+/A/B/C.

=== SIGNAL ===
Pair: {symbol} | Direction: {direction} | RR: {rr:.1f}:1 | SL: {sl_pct:.1f}%
BTC Regime: {btc_regime} | Fear&Greed: {fg_val} | Session: {session}
Multi-TF FVG: {multitf_confluence} | Funding: {funding_label}
{levels_str}{disc_str}

=== ACTUAL PRICE ACTION (15m, last 12 candles) ===
{ohlcv_str}

=== MARKET INTEL (CoinGecko + CoinDesk + CMC) ===
{intel_str}

=== CRITERIA ===
A+ = RR≥3.0 + confluence YES + London/NY session + BTC aligned + F&G 20-79 +
     funding neutral/opposite + bullish intel + strong volume CHoCH candle visible
A  = RR≥2.5 + most factors align + 1 minor weakness
B  = RR≥2.5 but weak session OR no confluence OR slightly crowded OR bearish intel
C  = Multiple red flags: old pump + no confluence + bad session + extreme funding +
     bearish intel + price discrepancy + weak candles

Analyze actual OHLCV — look for volume on CHoCH candle, clean structure, body size.

Reply ONLY in this exact format:
RATING: X
REASON: [max 18 words — most important factor]"""

    # ── Option 1: OpenAI (primary, paid — ~$0.0002 per call) ─────────────────
    if config.OPENAI_API_KEY and getattr(config, "SIGNAL_AI_RATING_ENABLED", True):
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as sess:
                async with sess.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                        "Content-Type":  "application/json",
                    },
                    json={
                        "model":       config.OPENAI_MODEL,
                        "max_tokens":  80,
                        "temperature": 0.1,
                        "messages":    [{"role": "user", "content": full_prompt}],
                    },
                ) as resp:
                    if resp.status == 200:
                        data   = await resp.json()
                        text   = data["choices"][0]["message"]["content"].strip()
                        rating = "N/A"
                        reason = "no reason"
                        for line in text.split("\n"):
                            if line.startswith("RATING:"):
                                raw = line.replace("RATING:","").strip().upper()
                                if raw in ("A+","A","B","C"): rating = raw
                            elif line.startswith("REASON:"):
                                reason = line.replace("REASON:","").strip()
                        if rating != "N/A":
                            logger.info(f"OpenAI: {symbol} {direction} → {rating} | {reason}")
                            return rating, reason
                    else:
                        logger.warning(f"OpenAI HTTP {resp.status}")
        except asyncio.TimeoutError:
            logger.warning("OpenAI timeout — falling back to rule-based")
        except Exception as exc:
            logger.warning(f"OpenAI error: {exc} — falling back")

    # ── Option 2: Ollama (optional free local LLM) ────────────────────────────
    if getattr(config, "OLLAMA_ENABLED", False):
        rating, reason = await _ollama_rate(full_prompt)
        if rating != "N/A":
            logger.info(f"Ollama: {symbol} {direction} → {rating}")
            return rating, reason

    # ── Option 3: Rule-based fallback (always works, free) ───────────────────
    rating, reason = _rule_based_rate(
        rr=rr, btc_regime=btc_regime, fg_val=fg_val, session=session,
        multitf_confluence=multitf_confluence, sl_pct=sl_pct,
        funding_label=funding_label, candle_score=candle_score,
        candle_obs=candle_obs, intel=intel, direction=direction,
        price_discrepancy=price_discrepancy,
    )
    logger.info(f"Rule: {symbol} {direction} → {rating} | {reason}")
    return rating, reason


def rating_emoji(rating: str) -> str:
    return {"A+": "🌟","A": "✅","B": "⚠️","C": "❌","N/A": "➖"}.get(rating, "➖")

def should_suppress(rating: str) -> bool:
    if not getattr(config, "SIGNAL_AI_SUPPRESS_LOW_RATING", False): return False
    return rating == "C"
