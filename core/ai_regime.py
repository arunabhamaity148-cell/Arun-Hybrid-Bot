"""
core/ai_regime.py — AI-Powered Market Regime Detection + Multi-Agent Cross-Check
Arunabha Hybrid Bot v1.0

দুটো advanced AI feature:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. REGIME DETECTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Market এখন কোন phase এ আছে সেটা AI classify করে।

4 phases (Wyckoff inspired):
  ACCUMULATION  — Smart money buy করছে quietly
                  Best for: LONG entries
  MARKUP        — Trending bull, retail joining
                  Best for: LONG, momentum trades
  DISTRIBUTION  — Smart money sell করছে into strength
                  Best for: SHORT entries, avoid LONG
  MARKDOWN      — Trending bear, panic selling
                  Best for: SHORT only

Cost: ~$0.0003/signal (OpenAI) — অথবা free (rule-based fallback)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. MULTI-AGENT CROSS-CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Signal generate হলে ২টা AI agent আলাদাভাবে দেখে:
  Bull Agent: "কেন এই trade নেওয়া উচিত?"
  Bear Agent: "কেন এই trade ভুল হতে পারে?"

Final confidence score বের হয়।
বড় disagreement = caution flag।

Cost: ~$0.0006/signal (2x OpenAI calls) — Railway free tier এ চলবে।
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import config

logger = logging.getLogger(__name__)


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class RegimeResult:
    phase:        str           # ACCUMULATION / MARKUP / DISTRIBUTION / MARKDOWN / UNKNOWN
    confidence:   int           # 0-100
    bias:         str           # LONG_BIAS / SHORT_BIAS / NEUTRAL
    reasoning:    str           # 1 sentence explanation
    signal_boost: int           # score bonus: +10 aligned, -5 against, 0 neutral
    caution:      bool = False  # True = phase mismatches signal direction

    def telegram_line(self) -> str:
        phase_emoji = {
            "ACCUMULATION": "📦", "MARKUP":       "🚀",
            "DISTRIBUTION": "🏭", "MARKDOWN":     "📉",
            "UNKNOWN":      "❓"
        }.get(self.phase, "❓")
        boost_str = f" (+{self.signal_boost}pts)" if self.signal_boost > 0 else \
                    f" ({self.signal_boost}pts)" if self.signal_boost < 0 else ""
        caution_str = " ⚠️" if self.caution else ""
        return (
            f"• Regime: {phase_emoji} {self.phase} "
            f"[{self.confidence}% conf]{boost_str}{caution_str}"
        )


@dataclass
class MultiAgentResult:
    bull_case:    str           # Bull agent এর argument
    bear_case:    str           # Bear agent এর argument
    confidence:   int           # 0-100 (bull wins হলে বেশি)
    verdict:      str           # PROCEED / CAUTION / SKIP
    score_adj:    int           # score adjustment: -10 to +10
    disagreement: bool          # True = agents strongly disagree

    def telegram_section(self) -> str:
        verdict_emoji = {"PROCEED": "✅", "CAUTION": "⚠️", "SKIP": "❌"}.get(self.verdict, "❓")
        lines = [f"\n🤝 <b>Agent Analysis:</b> {verdict_emoji} {self.verdict} [{self.confidence}% confidence]"]
        if self.bull_case:
            lines.append(f"  🟢 Bull: {self.bull_case}")
        if self.bear_case:
            lines.append(f"  🔴 Bear: {self.bear_case}")
        if self.disagreement:
            lines.append(f"  ⚠️ Agents strongly disagree — reduce size")
        return "\n".join(lines)


# ── OpenAI Helper ─────────────────────────────────────────────────────────────

async def _openai_call(prompt: str, max_tokens: int = 120, temperature: float = 0.2) -> Optional[str]:
    """Single OpenAI API call with timeout."""
    if not config.OPENAI_API_KEY:
        return None
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=12)
        ) as sess:
            async with sess.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       config.OPENAI_MODEL,
                    "max_tokens":  max_tokens,
                    "temperature": temperature,
                    "messages":    [{"role": "user", "content": prompt}],
                },
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    logger.warning(f"OpenAI HTTP {resp.status}")
                    return None
    except asyncio.TimeoutError:
        logger.warning("OpenAI timeout in regime detection")
        return None
    except Exception as exc:
        logger.warning(f"OpenAI error: {exc}")
        return None


async def _ollama_call(prompt: str) -> Optional[str]:
    """Ollama local LLM call."""
    if not getattr(config, "OLLAMA_ENABLED", False):
        return None
    url   = getattr(config, "OLLAMA_URL",   "http://localhost:11434")
    model = getattr(config, "OLLAMA_MODEL", "mistral")
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as sess:
            async with sess.post(
                f"{url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("response", "").strip()
    except Exception as exc:
        logger.debug(f"Ollama error: {exc}")
    return None


# ── Rule-Based Regime Detection (free fallback) ───────────────────────────────

def _rule_based_regime(
    btc_regime:   str,
    fg_val:       int,
    funding_rate: float,
    ofi_label:    str,
    price_change_24h: float,
    direction:    str,
) -> RegimeResult:
    """
    Wyckoff phase detection using available indicators.
    No API needed — always works.
    """
    score = 0  # positive = bullish/markup, negative = bearish/markdown

    # BTC regime
    if "BULL" in btc_regime.upper():  score += 30
    elif "BEAR" in btc_regime.upper(): score -= 30

    # Fear & Greed
    if fg_val >= 70:   score += 20    # greed = markup
    elif fg_val >= 50: score += 10
    elif fg_val <= 25: score -= 20    # fear = markdown
    elif fg_val <= 40: score -= 10

    # Price momentum
    if price_change_24h >= 5:    score += 20
    elif price_change_24h >= 2:  score += 10
    elif price_change_24h <= -5: score -= 20
    elif price_change_24h <= -2: score -= 10

    # OFI
    if ofi_label in ("STRONG_BUY", "BUY"):    score += 15
    elif ofi_label in ("STRONG_SELL", "SELL"): score -= 15

    # Funding (crowded = distribution sign)
    if abs(funding_rate) >= 0.08: score -= 10  # extreme = distribution

    # Classify
    if score >= 45:
        phase = "MARKUP"
        confidence = min(90, 50 + score)
        bias = "LONG_BIAS"
    elif score >= 15:
        phase = "ACCUMULATION"
        confidence = min(75, 40 + score)
        bias = "LONG_BIAS"
    elif score <= -45:
        phase = "MARKDOWN"
        confidence = min(90, 50 + abs(score))
        bias = "SHORT_BIAS"
    elif score <= -15:
        phase = "DISTRIBUTION"
        confidence = min(75, 40 + abs(score))
        bias = "SHORT_BIAS"
    else:
        phase = "UNKNOWN"
        confidence = 40
        bias = "NEUTRAL"

    # Direction alignment
    aligned = (direction == "LONG"  and bias == "LONG_BIAS") or \
              (direction == "SHORT" and bias == "SHORT_BIAS") or \
              bias == "NEUTRAL"

    signal_boost = 10 if aligned and phase not in ("UNKNOWN",) else \
                  -5 if not aligned else 0
    caution = not aligned and phase not in ("UNKNOWN",)

    reasoning_map = {
        "MARKUP":       "BTC bull + price momentum + greed zone",
        "ACCUMULATION": "quiet buying detected, low fear",
        "DISTRIBUTION": "high funding + price exhaustion signs",
        "MARKDOWN":     "BTC bear + price falling + fear rising",
        "UNKNOWN":      "mixed signals, no clear phase",
    }

    return RegimeResult(
        phase=phase,
        confidence=confidence,
        bias=bias,
        reasoning=reasoning_map.get(phase, ""),
        signal_boost=signal_boost,
        caution=caution,
    )


async def _ai_regime(
    symbol:       str,
    direction:    str,
    btc_regime:   str,
    fg_val:       int,
    funding_rate: float,
    ofi_label:    str,
    price_change_24h: float,
    intel_summary: str,
) -> RegimeResult:
    """AI-powered regime detection via OpenAI/Ollama."""

    prompt = f"""You are a market microstructure expert analyzing crypto market phase.

Data:
- Symbol: {symbol} | Direction sought: {direction}
- BTC Regime: {btc_regime}
- Fear & Greed: {fg_val}/100
- 24h Price Change: {price_change_24h:+.1f}%
- Funding Rate: {funding_rate:+.3f}%
- Order Flow: {ofi_label}
- Market Intel: {intel_summary}

Classify the current market PHASE using Wyckoff methodology:
ACCUMULATION = smart money quietly buying, low volatility, weak hands selling
MARKUP       = trending up, momentum building, retail FOMO starting  
DISTRIBUTION = smart money selling into strength, high volume, price stalling
MARKDOWN     = trending down, panic, lower highs/lows

Reply ONLY in this exact format (no other text):
PHASE: [ACCUMULATION/MARKUP/DISTRIBUTION/MARKDOWN/UNKNOWN]
CONFIDENCE: [0-100]
BIAS: [LONG_BIAS/SHORT_BIAS/NEUTRAL]
REASON: [max 12 words]"""

    response = await _openai_call(prompt, max_tokens=80) or \
               await _ollama_call(prompt)

    if not response:
        return _rule_based_regime(btc_regime, fg_val, funding_rate, ofi_label, price_change_24h, direction)

    # Parse response
    phase = "UNKNOWN"; confidence = 50; bias = "NEUTRAL"; reasoning = ""
    for line in response.split("\n"):
        line = line.strip()
        if line.startswith("PHASE:"):
            val = line.replace("PHASE:", "").strip().upper()
            if val in ("ACCUMULATION", "MARKUP", "DISTRIBUTION", "MARKDOWN", "UNKNOWN"):
                phase = val
        elif line.startswith("CONFIDENCE:"):
            try: confidence = int(line.replace("CONFIDENCE:", "").strip())
            except: pass
        elif line.startswith("BIAS:"):
            val = line.replace("BIAS:", "").strip().upper()
            if val in ("LONG_BIAS", "SHORT_BIAS", "NEUTRAL"): bias = val
        elif line.startswith("REASON:"):
            reasoning = line.replace("REASON:", "").strip()

    aligned = (direction == "LONG"  and bias == "LONG_BIAS") or \
              (direction == "SHORT" and bias == "SHORT_BIAS") or \
              bias == "NEUTRAL"

    signal_boost = 10 if aligned and confidence >= 60 else \
                  -5  if not aligned and confidence >= 60 else 0
    caution = not aligned and confidence >= 60

    logger.info(f"Regime {symbol}: {phase} [{confidence}%] {bias} → boost {signal_boost:+d}")

    return RegimeResult(
        phase=phase,
        confidence=confidence,
        bias=bias,
        reasoning=reasoning,
        signal_boost=signal_boost,
        caution=caution,
    )


# ── Multi-Agent Cross-Check ───────────────────────────────────────────────────

def _rule_based_multiagent(
    direction:    str,
    rr:           float,
    multitf:      bool,
    ofi_label:    str,
    cvd_diverging: bool,
    funding_label: str,
    regime_phase:  str,
    fg_val:        int,
) -> MultiAgentResult:
    """Rule-based multi-agent simulation — free fallback."""

    bull_points = 0
    bear_points = 0
    bull_args = []
    bear_args  = []

    # Bull case
    if rr >= 3.0:    bull_points += 2; bull_args.append(f"strong RR {rr:.1f}")
    if multitf:      bull_points += 2; bull_args.append("multi-TF aligned")
    if ofi_label in ("BUY", "STRONG_BUY") and direction == "LONG":
        bull_points += 2; bull_args.append("order flow bullish")
    if regime_phase in ("ACCUMULATION", "MARKUP") and direction == "LONG":
        bull_points += 2; bull_args.append(f"{regime_phase} phase")
    if 40 <= fg_val <= 70:
        bull_points += 1; bull_args.append("healthy sentiment")

    # Bear case
    if cvd_diverging: bear_points += 2; bear_args.append("CVD diverging")
    if funding_label in ("EXTREME_LONG", "HIGH_LONG") and direction == "LONG":
        bear_points += 2; bear_args.append("crowded longs")
    if ofi_label in ("SELL", "STRONG_SELL") and direction == "LONG":
        bear_points += 2; bear_args.append("selling pressure")
    if regime_phase in ("DISTRIBUTION", "MARKDOWN") and direction == "LONG":
        bear_points += 3; bear_args.append(f"phase mismatch: {regime_phase}")
    if fg_val >= 80:
        bear_points += 1; bear_args.append("extreme greed")

    total = bull_points + bear_points
    confidence = int((bull_points / total * 100)) if total > 0 else 50

    if confidence >= 65:   verdict = "PROCEED"
    elif confidence >= 45: verdict = "CAUTION"
    else:                  verdict = "SKIP"

    score_adj = 8 if verdict == "PROCEED" else \
                0 if verdict == "CAUTION" else -8

    disagreement = abs(bull_points - bear_points) >= 4 and \
                   min(bull_points, bear_points) >= 2

    return MultiAgentResult(
        bull_case=bull_args[0] if bull_args else "setup technically valid",
        bear_case=bear_args[0] if bear_args else "no major red flags",
        confidence=confidence,
        verdict=verdict,
        score_adj=score_adj,
        disagreement=disagreement,
    )


async def _ai_multiagent(
    symbol:     str,
    direction:  str,
    signal_summary: str,
) -> MultiAgentResult:
    """Two OpenAI calls — bull agent and bear agent — run in parallel."""

    bull_prompt = f"""You are an aggressive BULL trader who always wants to find reasons to enter a trade.

Signal: {symbol} {direction}
{signal_summary}

In MAX 10 words, give the SINGLE STRONGEST reason to take this trade.
Reply only with the reason, no labels."""

    bear_prompt = f"""You are a skeptical BEAR trader who always looks for reasons to avoid a trade.

Signal: {symbol} {direction}
{signal_summary}

In MAX 10 words, give the SINGLE BIGGEST risk or reason to AVOID this trade.
Reply only with the reason, no labels."""

    # Run both agents in parallel
    bull_resp, bear_resp = await asyncio.gather(
        _openai_call(bull_prompt, max_tokens=25, temperature=0.3),
        _openai_call(bear_prompt, max_tokens=25, temperature=0.3),
        return_exceptions=True,
    )

    # Handle failures
    if isinstance(bull_resp, Exception): bull_resp = None
    if isinstance(bear_resp, Exception): bear_resp = None

    if not bull_resp or not bear_resp:
        # Fall back to rule-based — parse summary for key fields
        return MultiAgentResult(
            bull_case=bull_resp or "setup technically valid",
            bear_case=bear_resp or "insufficient AI response",
            confidence=55,
            verdict="CAUTION",
            score_adj=0,
            disagreement=False,
        )

    bull_case = bull_resp.strip()[:80]
    bear_case  = bear_resp.strip()[:80]

    # Simple confidence: ask AI to judge
    judge_prompt = f"""Bull says: "{bull_case}"
Bear says: "{bear_case}"
For a {direction} trade on {symbol}, who makes a stronger point?
Reply only: BULL [0-100] or BEAR [0-100] (confidence score)"""

    judge_resp = await _openai_call(judge_prompt, max_tokens=10, temperature=0.1)

    confidence = 55  # default neutral
    if judge_resp:
        import re
        match = re.search(r'(BULL|BEAR)\s+(\d+)', judge_resp.upper())
        if match:
            side, score = match.group(1), int(match.group(2))
            confidence = score if side == "BULL" else (100 - score)
            confidence = max(10, min(90, confidence))

    if confidence >= 65:   verdict = "PROCEED"
    elif confidence >= 45: verdict = "CAUTION"
    else:                  verdict = "SKIP"

    score_adj = 8 if verdict == "PROCEED" else 0 if verdict == "CAUTION" else -8

    # Check disagreement: if both sides give strong arguments
    disagreement = len(bull_case) > 15 and len(bear_case) > 15 and \
                   45 <= confidence <= 60

    logger.info(
        f"MultiAgent {symbol}: Bull='{bull_case[:30]}' Bear='{bear_case[:30]}' "
        f"→ {verdict} [{confidence}%]"
    )

    return MultiAgentResult(
        bull_case=bull_case,
        bear_case=bear_case,
        confidence=confidence,
        verdict=verdict,
        score_adj=score_adj,
        disagreement=disagreement,
    )


# ── Main Public Functions ──────────────────────────────────────────────────────

async def get_regime(
    symbol:        str,
    direction:     str,
    btc_regime:    str,
    fg_val:        int,
    funding_rate:  float  = 0.0,
    ofi_label:     str    = "NEUTRAL",
    price_change_24h: float = 0.0,
    intel_summary: str    = "",
) -> RegimeResult:
    """
    Market regime detect করো।
    OpenAI → Ollama → Rule-based fallback।
    """
    if not getattr(config, "REGIME_DETECTION_ENABLED", True):
        return RegimeResult(
            phase="UNKNOWN", confidence=50, bias="NEUTRAL",
            reasoning="disabled", signal_boost=0, caution=False
        )

    if config.OPENAI_API_KEY or getattr(config, "OLLAMA_ENABLED", False):
        return await _ai_regime(
            symbol, direction, btc_regime, fg_val,
            funding_rate, ofi_label, price_change_24h, intel_summary
        )
    else:
        return _rule_based_regime(
            btc_regime, fg_val, funding_rate, ofi_label, price_change_24h, direction
        )


async def get_multiagent(
    symbol:    str,
    direction: str,
    rr:        float,
    multitf:   bool,
    ofi_label: str,
    cvd_diverging: bool,
    funding_label: str,
    regime_phase:  str,
    fg_val:        int,
    signal_summary: str = "",
) -> MultiAgentResult:
    """
    Multi-agent bull vs bear cross-check।
    OpenAI → Rule-based fallback।
    """
    if not getattr(config, "MULTI_AGENT_ENABLED", True):
        return MultiAgentResult(
            bull_case="", bear_case="", confidence=60,
            verdict="PROCEED", score_adj=0, disagreement=False
        )

    if config.OPENAI_API_KEY and signal_summary:
        return await _ai_multiagent(symbol, direction, signal_summary)
    else:
        return _rule_based_multiagent(
            direction, rr, multitf, ofi_label,
            cvd_diverging, funding_label, regime_phase, fg_val
        )
