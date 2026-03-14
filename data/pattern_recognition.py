"""
data/pattern_recognition.py — Candle Pattern Recognition
Arunabha Hybrid Bot v1.0

Historical candle patterns দেখে signal এর probability estimate করে।

দুটো layer:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer 1: Rule-Based Classic Patterns (FREE, always works)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Bullish: Hammer, Bullish Engulfing, Morning Star, 3 White Soldiers
  Bearish: Shooting Star, Bearish Engulfing, Evening Star, 3 Black Crows
  Neutral: Doji, Spinning Top

Score: প্রতিটা pattern এর ঐতিহাসিক reliability দেখে 0-100

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer 2: Ollama Local AI Pattern (FREE, optional)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ollama pull mistral → config তে OLLAMA_ENABLED=True করো
  AI নিজেই pattern বলবে + probability দেবে
  OpenAI use করে না — সম্পূর্ণ local, সম্পূর্ণ free

Cost: Zero। Ollama না থাকলে rule-based দিয়েই চলে।
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import config
from data.cache_manager import cache

logger = logging.getLogger(__name__)

_PATTERN_CACHE_SECONDS = 120


@dataclass
class PatternResult:
    symbol:      str
    direction:   str

    patterns_found: list[str] = field(default_factory=list)
    pattern_score:  int  = 50           # 0-100 (50 = neutral)
    pattern_label:  str  = "NEUTRAL"    # STRONG_BULL / BULL / NEUTRAL / BEAR / STRONG_BEAR
    reliability:    int  = 0            # 0-100 historical accuracy estimate
    score_bonus:    int  = 0            # -5 to +8 signal score bonus

    def telegram_line(self) -> str:
        if not self.patterns_found:
            return ""
        label_emoji = {
            "STRONG_BULL": "🟢🟢", "BULL": "🟢",
            "NEUTRAL":     "⬜",
            "BEAR":        "🔴",   "STRONG_BEAR": "🔴🔴"
        }.get(self.pattern_label, "⬜")

        patterns_str = " + ".join(self.patterns_found[:2])
        bonus_str = f" (+{self.score_bonus}pts)" if self.score_bonus > 0 else \
                    f" ({self.score_bonus}pts)" if self.score_bonus < 0 else ""
        return f"• Pattern: {label_emoji} {patterns_str} [{self.reliability}% hist.]{bonus_str}"


# ── Candle Helper Functions ───────────────────────────────────────────────────

def _body_size(o, c, h, l) -> float:
    """Candle body / total range ratio."""
    rng = h - l
    return abs(c - o) / rng if rng > 0 else 0


def _upper_wick(o, c, h) -> float:
    return h - max(o, c)


def _lower_wick(o, c, l) -> float:
    return min(o, c) - l


def _is_bull(o, c) -> bool:
    return c > o


def _is_bear(o, c) -> bool:
    return c < o


# ── Classic Pattern Detectors ─────────────────────────────────────────────────

def _detect_hammer(candles: list[dict]) -> Optional[tuple[str, int]]:
    """Hammer (bullish reversal) — small body, long lower wick."""
    if len(candles) < 2: return None
    c = candles[-1]
    o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])

    body = abs(cl - o)
    lower_wick = _lower_wick(o, cl, l)
    upper_wick = _upper_wick(o, cl, h)
    rng = h - l

    if rng == 0: return None
    if lower_wick >= 2 * body and upper_wick <= 0.1 * rng and _body_size(o, cl, h, l) <= 0.35:
        return "Hammer", 65


def _detect_shooting_star(candles: list[dict]) -> Optional[tuple[str, int]]:
    """Shooting Star (bearish reversal) — small body, long upper wick."""
    if len(candles) < 2: return None
    c = candles[-1]
    o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])

    upper_wick = _upper_wick(o, cl, h)
    lower_wick = _lower_wick(o, cl, l)
    body = abs(cl - o)
    rng = h - l

    if rng == 0: return None
    if upper_wick >= 2 * body and lower_wick <= 0.1 * rng and _body_size(o, cl, h, l) <= 0.35:
        return "Shooting Star", 62


def _detect_engulfing(candles: list[dict]) -> Optional[tuple[str, int]]:
    """Bullish/Bearish Engulfing."""
    if len(candles) < 2: return None
    prev = candles[-2]
    curr = candles[-1]

    po, pc = float(prev["open"]), float(prev["close"])
    co, cc = float(curr["open"]), float(curr["close"])

    # Bullish engulfing: prev bear, curr bull, curr body covers prev body
    if _is_bear(po, pc) and _is_bull(co, cc):
        if co <= pc and cc >= po:  # curr engulfs prev
            return "Bullish Engulfing", 72

    # Bearish engulfing: prev bull, curr bear, curr body covers prev body
    if _is_bull(po, pc) and _is_bear(co, cc):
        if co >= pc and cc <= po:
            return "Bearish Engulfing", 70

    return None


def _detect_morning_evening_star(candles: list[dict]) -> Optional[tuple[str, int]]:
    """Morning Star (bullish) / Evening Star (bearish) — 3 candle pattern."""
    if len(candles) < 3: return None

    c1, c2, c3 = candles[-3], candles[-2], candles[-1]
    o1, c1v = float(c1["open"]), float(c1["close"])
    o2, c2v = float(c2["open"]), float(c2["close"])
    o3, c3v = float(c3["open"]), float(c3["close"])

    body1 = abs(c1v - o1)
    body2 = abs(c2v - o2)
    body3 = abs(c3v - o3)

    # Morning Star: big bear → small doji → big bull
    if _is_bear(o1, c1v) and body2 <= 0.3 * body1 and _is_bull(o3, c3v):
        if c3v >= o1 - body1 * 0.5:  # third candle recovers >50% of first
            return "Morning Star", 78

    # Evening Star: big bull → small doji → big bear
    if _is_bull(o1, c1v) and body2 <= 0.3 * body1 and _is_bear(o3, c3v):
        if c3v <= o1 + body1 * 0.5:
            return "Evening Star", 75

    return None


def _detect_three_soldiers_crows(candles: list[dict]) -> Optional[tuple[str, int]]:
    """Three White Soldiers (bullish) / Three Black Crows (bearish)."""
    if len(candles) < 3: return None

    last3 = candles[-3:]
    opens  = [float(c["open"])  for c in last3]
    closes = [float(c["close"]) for c in last3]
    highs  = [float(c["high"])  for c in last3]
    lows   = [float(c["low"])   for c in last3]

    # Three White Soldiers: 3 consecutive bull candles, each closing higher
    if all(_is_bull(opens[i], closes[i]) for i in range(3)):
        if closes[0] < closes[1] < closes[2]:  # each higher close
            bodies = [abs(closes[i] - opens[i]) for i in range(3)]
            avg_body = sum(bodies) / 3
            ranges   = [highs[i] - lows[i] for i in range(3)]
            avg_range = sum(ranges) / 3
            if avg_body >= 0.5 * avg_range:  # strong bodies
                return "3 White Soldiers", 80

    # Three Black Crows: 3 consecutive bear candles, each lower
    if all(_is_bear(opens[i], closes[i]) for i in range(3)):
        if closes[0] > closes[1] > closes[2]:  # each lower close
            bodies = [abs(closes[i] - opens[i]) for i in range(3)]
            avg_body = sum(bodies) / 3
            ranges   = [highs[i] - lows[i] for i in range(3)]
            avg_range = sum(ranges) / 3
            if avg_body >= 0.5 * avg_range:
                return "3 Black Crows", 77

    return None


def _detect_doji(candles: list[dict]) -> Optional[tuple[str, int]]:
    """Doji — indecision (body very small)."""
    if not candles: return None
    c = candles[-1]
    o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])

    if _body_size(o, cl, h, l) <= 0.05:
        return "Doji", 50  # neutral


# ── Pattern Scoring ───────────────────────────────────────────────────────────

_BULLISH_PATTERNS = {"Hammer", "Bullish Engulfing", "Morning Star", "3 White Soldiers"}
_BEARISH_PATTERNS = {"Shooting Star", "Bearish Engulfing", "Evening Star", "3 Black Crows"}
_NEUTRAL_PATTERNS = {"Doji"}


def _score_patterns(patterns: list[tuple[str, int]], direction: str) -> tuple[int, str, int, int]:
    """
    Pattern list থেকে score, label, reliability, bonus বের করো।
    Direction-aware: bullish pattern for LONG = good, for SHORT = bad
    """
    if not patterns:
        return 50, "NEUTRAL", 0, 0

    total_reliability = sum(r for _, r in patterns)
    avg_reliability   = total_reliability // len(patterns)

    bull_count = sum(1 for n, _ in patterns if n in _BULLISH_PATTERNS)
    bear_count  = sum(1 for n, _ in patterns if n in _BEARISH_PATTERNS)

    if bull_count > bear_count:
        label = "STRONG_BULL" if bull_count >= 2 else "BULL"
        raw_score = 65 + (bull_count * 10)
    elif bear_count > bull_count:
        label = "STRONG_BEAR" if bear_count >= 2 else "BEAR"
        raw_score = 35 - (bear_count * 10)
    else:
        label = "NEUTRAL"
        raw_score = 50

    raw_score = max(0, min(100, raw_score))

    # Direction-aware bonus
    if direction == "LONG":
        if label in ("STRONG_BULL",): bonus = 8
        elif label == "BULL":          bonus = 5
        elif label == "NEUTRAL":       bonus = 0
        elif label == "BEAR":          bonus = -3
        else:                           bonus = -5  # STRONG_BEAR
    else:  # SHORT
        if label in ("STRONG_BEAR",):  bonus = 8
        elif label == "BEAR":          bonus = 5
        elif label == "NEUTRAL":       bonus = 0
        elif label == "BULL":          bonus = -3
        else:                           bonus = -5  # STRONG_BULL

    return raw_score, label, avg_reliability, bonus


# ── Optional Ollama Pattern Analysis ─────────────────────────────────────────

async def _ollama_pattern(candles: list[dict], direction: str) -> Optional[tuple[str, int]]:
    """Ollama local AI — optional, সম্পূর্ণ free।"""
    if not getattr(config, "OLLAMA_ENABLED", False) or len(candles) < 5:
        return None

    ohlcv_str = "\n".join(
        f"{'🟢' if float(c['close'])>=float(c['open']) else '🔴'} "
        f"O:{float(c['open']):.4g} H:{float(c['high']):.4g} "
        f"L:{float(c['low']):.4g} C:{float(c['close']):.4g}"
        for c in candles[-6:]
    )

    prompt = f"""Analyze these last 6 candles for a {direction} trade:
{ohlcv_str}

Identify the most significant candlestick pattern if any.
Reply in this exact format:
PATTERN: [name or NONE]
BULLISH_PROB: [0-100]
REASON: [max 8 words]"""

    try:
        import aiohttp
        url   = getattr(config, "OLLAMA_URL",   "http://localhost:11434")
        model = getattr(config, "OLLAMA_MODEL", "mistral")

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as sess:
            async with sess.post(
                f"{url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                text = data.get("response", "")

                pattern_name = "NONE"
                bull_prob    = 50
                for line in text.split("\n"):
                    line = line.strip()
                    if line.startswith("PATTERN:"):
                        pattern_name = line.replace("PATTERN:", "").strip()
                    elif line.startswith("BULLISH_PROB:"):
                        try: bull_prob = int(line.replace("BULLISH_PROB:", "").strip())
                        except: pass

                if pattern_name and pattern_name != "NONE":
                    return f"AI: {pattern_name}", bull_prob

    except Exception as exc:
        logger.debug(f"Ollama pattern error: {exc}")

    return None


# ── Main Function ─────────────────────────────────────────────────────────────

async def get_patterns(symbol: str, direction: str, candles: list[dict]) -> PatternResult:
    """
    Main function — candle pattern recognition।
    Rule-based সবসময় চলে + Ollama optional।
    """
    if not getattr(config, "PATTERN_RECOGNITION_ENABLED", True) or len(candles) < 3:
        return PatternResult(symbol=symbol, direction=direction)

    cache_key = f"patterns:{symbol}:{direction}:{len(candles)}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    patterns: list[tuple[str, int]] = []

    # Run all rule-based detectors
    detectors = [
        _detect_hammer,
        _detect_shooting_star,
        _detect_engulfing,
        _detect_morning_evening_star,
        _detect_three_soldiers_crows,
        _detect_doji,
    ]

    for detector in detectors:
        result = detector(candles)
        if result:
            patterns.append(result)

    # Optional Ollama enhancement
    ollama_result = await _ollama_pattern(candles, direction)
    if ollama_result:
        patterns.append(ollama_result)

    # Score
    score, label, reliability, bonus = _score_patterns(patterns, direction)

    result = PatternResult(
        symbol=symbol,
        direction=direction,
        patterns_found=[name for name, _ in patterns],
        pattern_score=score,
        pattern_label=label,
        reliability=reliability,
        score_bonus=bonus,
    )

    await cache.set(cache_key, result, ttl=_PATTERN_CACHE_SECONDS)

    if patterns:
        logger.debug(
            f"Patterns {symbol}: {[n for n,_ in patterns]} → "
            f"{label} bonus={bonus:+d}"
        )

    return result
