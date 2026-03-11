"""
filters/rr_validator.py — Filter 7: Risk/Reward Validation
Real RR = tp2_dist / sl_dist >= MIN_RR_RATIO (2.5).
"""

import logging
from typing import Tuple, Optional

import config

logger = logging.getLogger(__name__)


def calculate_levels(direction: str, entry: float, grab_level: float) -> dict:
    buffer = grab_level * config.SL_BUFFER_PCT

    if direction == "LONG":
        sl = grab_level - buffer
        sl_distance = entry - sl
    else:
        sl = grab_level + buffer
        sl_distance = sl - entry

    if sl_distance <= 0:
        return {"error": f"SL distance is zero or negative (entry={entry:.8g}, grab={grab_level:.8g})"}

    if sl_distance / entry < 0.0005:
        return {"error": f"SL distance too small ({sl_distance/entry*100:.3f}%) — likely bad grab level"}

    tp1_dist = sl_distance * 1.5
    tp2_dist = sl_distance * 3.0

    if direction == "LONG":
        tp1 = entry + tp1_dist
        tp2 = entry + tp2_dist
    else:
        tp1 = entry - tp1_dist
        tp2 = entry - tp2_dist

    rr = tp2_dist / sl_distance
    sl_pct = abs(sl_distance / entry) * 100
    tp1_pct = abs(tp1_dist / entry) * 100
    tp2_pct = abs(tp2_dist / entry) * 100

    return {
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "rr": round(rr, 2),
        "sl_distance": sl_distance,
        "sl_pct": round(sl_pct, 2),
        "tp1_pct": round(tp1_pct, 2),
        "tp2_pct": round(tp2_pct, 2),
    }


def check_rr_validator(direction: str, entry: float, grab_level: float) -> Tuple[bool, str, Optional[dict]]:
    try:
        if entry <= 0 or grab_level <= 0:
            msg = f"RR: Invalid prices (entry={entry}, grab={grab_level}) — skip ❌"
            return False, msg, None

        levels = calculate_levels(direction, entry, grab_level)

        if "error" in levels:
            msg = f"RR: {levels['error']} — skip ❌"
            return False, msg, None

        rr = levels["rr"]
        sl_pct = levels["sl_pct"]

        if rr >= config.MIN_RR_RATIO:
            msg = (
                f"RR: {rr:.2f}:1 "
                f"(SL -{sl_pct:.2f}%, TP1 +{levels['tp1_pct']:.2f}%, TP2 +{levels['tp2_pct']:.2f}%) "
                f"— approved ✅"
            )
            return True, msg, levels
        else:
            msg = (
                f"RR: {rr:.2f}:1 — below minimum {config.MIN_RR_RATIO}:1 "
                f"(SL dist={levels['sl_distance']:.8g}) — skip ❌"
            )
            return False, msg, None

    except Exception as exc:
        msg = f"RR: Unexpected error ({exc}) — skip ❌"
        logger.warning(f"RR validation error: {exc}", exc_info=True)
        return False, msg, None
