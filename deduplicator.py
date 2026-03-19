"""
Cross-platform deduplication (Phase 3 Extended).

Two listings are considered the same property when ALL of:
  • rent matches exactly
  • area within ±0.5 ping
  • floor number matches (or both unknown)
  • district matches (case-insensitive)
  • street name shares a common token (or both empty)

When a duplicate is found, we keep the first-seen listing but attach
additional source URLs from duplicates.
"""

import logging
from typing import Iterable

logger = logging.getLogger(__name__)


def _area_close(a1: float, a2: float, tol: float = 0.5) -> bool:
    if a1 == 0 or a2 == 0:
        return False   # unknown area → don't merge blindly
    return abs(a1 - a2) <= tol


def _street_overlap(s1: str, s2: str) -> bool:
    """True when both are empty OR share at least one common token."""
    s1, s2 = s1.strip(), s2.strip()
    if not s1 and not s2:
        return True
    if not s1 or not s2:
        return False
    # Split on common delimiters and check for shared token
    tokens1 = set(t for t in s1.replace("路", " ").replace("街", " ").split() if t)
    tokens2 = set(t for t in s2.replace("路", " ").replace("街", " ").split() if t)
    return bool(tokens1 & tokens2)


def _is_duplicate(a: dict, b: dict, area_tol: float = 0.5) -> bool:
    if a["rent"] != b["rent"]:
        return False
    if not _area_close(a["area"], b["area"], area_tol):
        return False
    # Floor: both unknown (0) counts as match
    if a["floor"] != b["floor"]:
        return False
    if a["district"].lower() != b["district"].lower():
        return False
    if not _street_overlap(a["street"], b["street"]):
        return False
    return True


def deduplicate(
    listings: list[dict],
    area_tolerance: float = 0.5,
) -> list[dict]:
    """
    Remove cross-platform duplicates from a list of normalised listings.

    The canonical entry keeps the first-seen listing's data, but its
    'extra_urls' list is populated with URLs from duplicates.

    Returns deduplicated list preserving original order.
    """
    result: list[dict] = []

    for listing in listings:
        # Skip same-source duplicates silently (crawlers handle that)
        matched = False
        for canonical in result:
            if canonical["source"] == listing["source"]:
                continue   # different-source check only
            if _is_duplicate(canonical, listing, area_tolerance):
                # Merge: attach alternate URL
                canonical.setdefault("extra_urls", [])
                alt = {"source": listing["source"], "url": listing["url"]}
                if alt not in canonical["extra_urls"]:
                    canonical["extra_urls"].append(alt)
                logger.debug(
                    "Dedup: merged %s:%s into %s:%s",
                    listing["source"], listing["source_id"],
                    canonical["source"], canonical["source_id"],
                )
                matched = True
                break

        if not matched:
            entry = dict(listing)
            entry.setdefault("extra_urls", [])
            result.append(entry)

    logger.info("Dedup: %d listings → %d after deduplication", len(listings), len(result))
    return result
