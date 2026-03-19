"""
591 租屋網 crawler.

Uses the 591 JSON API directly (no Playwright required unless cfg sets
use_playwright_for_591: true).

API flow:
  1. GET https://rent.591.com.tw/ → collect session cookie & CSRF token
  2. GET /home/search/rsList with search params → JSON listing pages
  3. (optional) GET /home/<id> for full detail (elevator / cooking tags)
"""

import logging
import re
from typing import Iterator

from .base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

_BASE = "https://rent.591.com.tw"
_LIST_API = f"{_BASE}/home/search/rsList"
_CSRF_RE = re.compile(r'"csrf-token"\s+content="([^"]+)"')

# 591 option codes
_OPTION_MAP = {
    "cook": "cook",      # 可開伙
    "lift": "lift",      # 有電梯
    "pet":  "pet",       # 可養寵物
}

# 591 kind codes (property type)
# 1=整層住家 2=獨立套房 3=分租套房 4=雅房 8=其他
# Note: some 591 docs list 獨立套房 as kind=3; adjust if needed.
_KIND_591 = {
    1: "整層住家",
    2: "獨立套房",
    3: "分租套房",
    4: "雅房",
}

PAGE_SIZE = 30


class Crawler591(BaseCrawler):
    SOURCE = "591"

    def _init_session(self) -> str:
        """Visit the homepage to obtain cookies and extract CSRF token."""
        resp = self.get(_BASE + "/")
        # Try to extract from meta tag
        m = _CSRF_RE.search(resp.text)
        if m:
            csrf = m.group(1)
            logger.debug("591 CSRF token: %s", csrf[:12] + "...")
            return csrf
        # Fallback: token from cookie
        csrf = self.session.cookies.get("XSRF-TOKEN", "")
        if not csrf:
            csrf = self.session.cookies.get("591_new_session", "")
        logger.debug("591 CSRF from cookie: %s", csrf[:12] + "..." if csrf else "(none)")
        return csrf

    def _build_params(self, kind: int, first_row: int = 0) -> dict:
        search = self.cfg.get("search", {})
        params: dict = {
            "is_new_list": 1,
            "type": 1,
            "searchtype": 1,
            "region": search.get("region", 1),
            "kind": kind,
            "rentprice": f"0,{search.get('max_rent', 38000)}",
            "area": f"{search.get('min_area', 20)},",
            "firstRow": first_row,
            "totalRows": "",
        }
        if search.get("cooking_required", True):
            params["option"] = "cook"
        return params

    def _fetch_page(self, csrf: str, kind: int, first_row: int) -> dict:
        headers = {
            "X-CSRF-TOKEN": csrf,
            "Referer": _BASE + "/",
            "deviceid": self._device_id(),
        }
        params = self._build_params(kind, first_row)
        resp = self.get(_LIST_API, params=params, headers=headers)
        return resp.json()

    @staticmethod
    def _device_id() -> str:
        import uuid
        return str(uuid.uuid4()).replace("-", "")

    def crawl(self) -> Iterator[dict]:
        types: list[int] = self.cfg.get("search", {}).get("types", [1, 3])

        try:
            csrf = self._init_session()
        except Exception as exc:
            logger.error("591 session init failed: %s", exc)
            return

        for kind in types:
            kind_name = _KIND_591.get(kind, str(kind))
            logger.info("591: crawling kind=%d (%s)", kind, kind_name)
            first_row = 0
            total = None

            while True:
                try:
                    data = self._fetch_page(csrf, kind, first_row)
                except Exception as exc:
                    logger.error("591 page fetch error (kind=%d row=%d): %s", kind, first_row, exc)
                    break

                status = data.get("status")
                if status != 1 and status != "1":
                    logger.warning("591 API returned status=%s", status)
                    break

                inner = data.get("data") or data.get("records") or {}
                if isinstance(inner, dict):
                    items = inner.get("data") or inner.get("records") or []
                    if total is None:
                        total = int(inner.get("totalRows", 0) or 0)
                elif isinstance(inner, list):
                    items = inner
                    if total is None:
                        total = len(items)
                else:
                    logger.warning("591 unexpected data shape: %s", type(inner))
                    break

                if not items:
                    break

                for item in items:
                    item["_kind_name"] = kind_name
                    yield item

                first_row += PAGE_SIZE
                if total and first_row >= total:
                    break

            logger.info("591: done kind=%d, fetched up to %d rows", kind, first_row)
