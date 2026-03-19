"""
Filtering logic (Phase 2 + Phase 3).

apply_filters(listing, cfg) → (passes: bool, reasons: list[str], notes: list[str])
  passes  – True means the listing survives all hard filters
  reasons – list of rejection reasons (non-empty when passes=False)
  notes   – human-readable annotations added to the report entry
            (e.g. ⚠ furniture warning, ⭐ empty unit badge)
"""

import re
import logging
from typing import Any

from mrt_data import is_within_mrt_distance

logger = logging.getLogger(__name__)

_ROOFTOP_RE = re.compile(r"頂樓加蓋|頂加")


# ────────────────────────────────────────────────────────────────────────────
# Floor & Elevator filter  (Phase 2 §1)
# ────────────────────────────────────────────────────────────────────────────

def _floor_elevator_check(listing: dict, cfg: dict) -> tuple[bool, str]:
    """
    Returns (passes, rejection_reason).
    rejection_reason is empty string when passes=True.
    """
    floor_cfg = cfg.get("filters", {}).get("floor", {})
    elevator_from = floor_cfg.get("elevator_required_from", 3)
    exclude_floor_nums: list[int] = floor_cfg.get("exclude_floor_numbers", [0, 1])
    exclude_kws: list[str] = floor_cfg.get("exclude_keywords", ["頂樓加蓋", "頂加"])

    floor = listing.get("floor", 0)
    title = listing.get("title", "")
    tags = listing.get("tags", [])
    tag_str = " ".join(tags)

    # Exclude rooftop additions by keyword in title or tags
    for kw in exclude_kws:
        if kw in title or kw in tag_str:
            return False, f"排除：含「{kw}」關鍵字"

    # Exclude basement
    if floor == -1:
        return False, "排除：地下室"

    # Exclude specified floor numbers (default: 0=unknown skipped below, 1=1F)
    if floor in exclude_floor_nums and floor != 0:
        return False, f"排除：{floor} 樓"

    # Floor unknown (0) — we can't verify, keep it but note it
    if floor == 0:
        return True, ""

    # 2F: keep unconditionally
    if floor == 2:
        return True, ""

    # 3F and above: require elevator tag
    if floor >= elevator_from:
        if listing.get("has_elevator") is True:
            return True, ""
        # has_elevator is None (unknown) or False → filter out
        return False, f"排除：{floor} 樓且無「有電梯」標籤"

    return True, ""


# ────────────────────────────────────────────────────────────────────────────
# Furniture annotation  (Phase 2 §2)
# ────────────────────────────────────────────────────────────────────────────

def _furniture_note(listing: dict) -> str:
    """Return annotation string (may be empty)."""
    furniture = listing.get("furniture", "unknown")
    if furniture == "move_in_ready":
        return "⚠️ 拎包入住：可能有電視/床墊，需與房東協商撤走"
    if furniture in ("empty", "unknown"):
        return "⭐ 極佳物件：適合自備家具"
    return ""


# ────────────────────────────────────────────────────────────────────────────
# MRT proximity filter  (Phase 3)
# ────────────────────────────────────────────────────────────────────────────

def _mrt_check(listing: dict, cfg: dict) -> tuple[bool, str, str]:
    """
    Returns (passes, rejection_reason, mrt_note).
    mrt_note is a human-readable string like '近忠孝復興站 (320 m)'.
    """
    mrt_cfg = cfg.get("mrt", {})
    if not mrt_cfg.get("enabled", True):
        return True, "", ""

    lat = listing.get("latitude")
    lon = listing.get("longitude")

    if lat is None or lon is None:
        # No coordinates — can't filter, keep but note
        return True, "", "（無座標，未檢查捷運距離）"

    max_m = mrt_cfg.get("max_distance_meters", 800)
    line_groups: list[str] | None = mrt_cfg.get("relevant_lines") or None

    passes, station_name, dist = is_within_mrt_distance(lat, lon, max_m, line_groups)

    dist_int = int(round(dist))
    note = f"近{station_name}站 ({dist_int} m)"

    if not passes:
        return False, f"排除：距最近捷運站 {dist_int} m > {max_m} m", note

    return True, "", note


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────

def apply_filters(
    listing: dict, cfg: dict
) -> tuple[bool, list[str], list[str]]:
    """
    Run all hard filters on a normalised listing.

    Returns:
        passes  (bool)       – True if listing survives all hard filters
        reasons (list[str])  – rejection reasons (empty when passes=True)
        notes   (list[str])  – annotations for the report
    """
    reasons: list[str] = []
    notes: list[str] = []

    # ── Floor / Elevator ──────────────────────────────────────────
    ok, reason = _floor_elevator_check(listing, cfg)
    if not ok:
        reasons.append(reason)
        return False, reasons, notes

    # ── Furniture annotation ──────────────────────────────────────
    furn_note = _furniture_note(listing)
    if furn_note:
        notes.append(furn_note)

    # ── MRT proximity ─────────────────────────────────────────────
    ok, reason, mrt_note = _mrt_check(listing, cfg)
    if mrt_note:
        notes.append(mrt_note)
    if not ok:
        reasons.append(reason)
        return False, reasons, notes

    return True, [], notes
