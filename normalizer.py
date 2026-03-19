"""
Unified Listing data model and per-source normalisers.

All crawlers produce raw dicts; normalise() converts them into a
standard Listing dict before filtering/deduplication.

Standard Listing fields:
    source          str     "591" | "ptt" | "dcard" | ...
    source_id       str     unique ID within that source
    url             str     canonical link to the listing
    title           str
    rent            int     TWD/month  (0 if unknown)
    area            float   坪         (0 if unknown)
    rooms           int     number of bedrooms  (0 if unknown)
    living_rooms    int     number of living rooms
    floor           int     floor number (0 = unknown, -1 = basement)
    total_floors    int     total floors in building (0 = unknown)
    has_elevator    bool | None
    can_cook        bool | None
    furniture       str     "empty" | "move_in_ready" | "partial" | "unknown"
    tags            list[str]
    district        str     行政區 e.g. "信義區"
    street          str     street name (best-effort)
    latitude        float | None
    longitude       float | None
    raw             dict    original data for debugging
"""

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── helpers ──────────────────────────────────────────────────────────────────

_COOKING_KEYWORDS = re.compile(r"可開伙|天然氣|瓦斯爐|可煮飯|開伙", re.IGNORECASE)
_FURNISHED_KEYWORDS = re.compile(r"附全套家具|家具齊全|全套家具|拎包入住", re.IGNORECASE)
_EMPTY_KEYWORDS = re.compile(r"空屋|空置", re.IGNORECASE)
_ROOFTOP_KEYWORDS = re.compile(r"頂樓加蓋|頂加", re.IGNORECASE)
_ELEVATOR_KEYWORDS = re.compile(r"有電梯|附電梯|含電梯", re.IGNORECASE)
_FLOOR_PATTERN = re.compile(r"(\d+)\s*[Ff樓]")
_BASEMENT_PATTERN = re.compile(r"[Bb]\d*|地下", re.IGNORECASE)


def _parse_floor(floor_str: str) -> tuple[int, int]:
    """
    Parse '3F/12F' or '3樓/12樓' → (3, 12).
    Returns (0, 0) on failure.
    """
    if not floor_str:
        return 0, 0

    if _BASEMENT_PATTERN.search(floor_str.split("/")[0]):
        return -1, 0

    nums = _FLOOR_PATTERN.findall(floor_str)
    if len(nums) >= 2:
        return int(nums[0]), int(nums[1])
    if len(nums) == 1:
        return int(nums[0]), 0
    return 0, 0


def _detect_furniture(tags: list[str], text: str) -> str:
    tag_str = " ".join(tags)
    if any(t in tag_str for t in ["拎包入住"]) or _FURNISHED_KEYWORDS.search(text):
        return "move_in_ready"
    if _EMPTY_KEYWORDS.search(tag_str) or _EMPTY_KEYWORDS.search(text):
        return "empty"
    return "unknown"


def _detect_cooking(tags: list[str], text: str) -> bool | None:
    if _COOKING_KEYWORDS.search(" ".join(tags)) or _COOKING_KEYWORDS.search(text):
        return True
    return None   # unknown — not False, since absence of tag ≠ not allowed


def _detect_elevator(tags: list[str], text: str) -> bool | None:
    if _ELEVATOR_KEYWORDS.search(" ".join(tags)) or _ELEVATOR_KEYWORDS.search(text):
        return True
    return None  # absence of tag doesn't definitively mean no elevator


# ── per-source normalisers ────────────────────────────────────────────────────

def _norm_591(raw: dict) -> dict:
    tags = raw.get("tags") or []
    tag_names = [t.get("name", t) if isinstance(t, dict) else str(t) for t in tags]

    floor_str = raw.get("floor_str", "")
    floor_num, total_floors = _parse_floor(floor_str)

    full_text = f"{raw.get('title', '')} {raw.get('note', '')} {raw.get('desc', '')}"

    post_id = str(raw.get("post_id") or raw.get("id", ""))
    return {
        "source": "591",
        "source_id": post_id,
        "url": f"https://rent.591.com.tw/home/{post_id}",
        "title": raw.get("title", "").strip(),
        "rent": int(raw.get("price", 0) or 0),
        "area": float(raw.get("area", 0) or 0),
        "rooms": int(raw.get("room", 0) or 0),
        "living_rooms": int(raw.get("living", 0) or 0),
        "floor": floor_num,
        "total_floors": total_floors,
        "has_elevator": _detect_elevator(tag_names, full_text),
        "can_cook": _detect_cooking(tag_names, full_text),
        "furniture": _detect_furniture(tag_names, full_text),
        "tags": tag_names,
        "district": raw.get("section_name", ""),
        "street": raw.get("street_name", ""),
        "latitude": raw.get("lat") and float(raw["lat"]) or None,
        "longitude": raw.get("lng") and float(raw["lng"]) or None,
        "raw": raw,
    }


def _norm_ptt(raw: dict) -> dict:
    text = f"{raw.get('title', '')} {raw.get('body', '')}"
    tags: list[str] = []

    # Try to extract rent from title/body
    rent_match = re.search(r"租金[：:]\s*(\d+)", text) or re.search(r"\$\s*(\d{3,6})", text)
    rent = int(rent_match.group(1)) if rent_match else 0

    area_match = re.search(r"(\d+(?:\.\d+)?)\s*坪", text)
    area = float(area_match.group(1)) if area_match else 0.0

    floor_match = re.search(r"(\d+)\s*[/／]\s*(\d+)\s*[樓Ff]", text)
    if floor_match:
        floor_num, total_floors = int(floor_match.group(1)), int(floor_match.group(2))
    else:
        floor_match2 = re.search(r"(\d+)\s*樓", text)
        floor_num = int(floor_match2.group(1)) if floor_match2 else 0
        total_floors = 0

    post_id = str(raw.get("post_id", raw.get("url", "").split("/")[-1].replace(".html", "")))

    return {
        "source": "ptt",
        "source_id": post_id,
        "url": raw.get("url", ""),
        "title": raw.get("title", "").strip(),
        "rent": rent,
        "area": area,
        "rooms": 0,
        "living_rooms": 0,
        "floor": floor_num,
        "total_floors": total_floors,
        "has_elevator": _detect_elevator(tags, text),
        "can_cook": _detect_cooking(tags, text),
        "furniture": _detect_furniture(tags, text),
        "tags": tags,
        "district": raw.get("district", ""),
        "street": raw.get("street", ""),
        "latitude": None,
        "longitude": None,
        "raw": raw,
    }


def _norm_dcard(raw: dict) -> dict:
    text = f"{raw.get('title', '')} {raw.get('excerpt', '')} {raw.get('content', '')}"
    tags: list[str] = raw.get("topics", [])

    rent_match = re.search(r"租金[：:]\s*(\d+)", text) or re.search(r"\$\s*(\d{3,6})", text)
    rent = int(rent_match.group(1)) if rent_match else 0

    area_match = re.search(r"(\d+(?:\.\d+)?)\s*坪", text)
    area = float(area_match.group(1)) if area_match else 0.0

    floor_num, total_floors = 0, 0
    floor_match = re.search(r"(\d+)\s*[/／]\s*(\d+)\s*[樓Ff]", text)
    if floor_match:
        floor_num, total_floors = int(floor_match.group(1)), int(floor_match.group(2))

    post_id = str(raw.get("id", ""))

    return {
        "source": "dcard",
        "source_id": post_id,
        "url": f"https://www.dcard.tw/f/rent/p/{post_id}",
        "title": raw.get("title", "").strip(),
        "rent": rent,
        "area": area,
        "rooms": 0,
        "living_rooms": 0,
        "floor": floor_num,
        "total_floors": total_floors,
        "has_elevator": _detect_elevator(tags, text),
        "can_cook": _detect_cooking(tags, text),
        "furniture": _detect_furniture(tags, text),
        "tags": tags,
        "district": raw.get("district", ""),
        "street": "",
        "latitude": None,
        "longitude": None,
        "raw": raw,
    }


_NORMALISERS = {
    "591": _norm_591,
    "ptt": _norm_ptt,
    "dcard": _norm_dcard,
}


def normalize(source: str, raw: dict) -> dict | None:
    """Normalise a raw crawler dict into a standard Listing dict."""
    fn = _NORMALISERS.get(source)
    if fn is None:
        logger.warning("No normaliser for source '%s'", source)
        return None
    try:
        return fn(raw)
    except Exception as exc:
        logger.error("Normalisation failed for %s: %s", source, exc, exc_info=True)
        return None
