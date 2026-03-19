"""
Dcard 租屋版 crawler.

Uses the public Dcard API:
  GET https://www.dcard.tw/_api/forums/rent/posts?limit=30&before=<cursor>

Filters for Taipei posts by keyword scan.
"""

import logging
import re
from typing import Iterator

from .base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

_API_URL = "https://www.dcard.tw/_api/forums/rent/posts"
_TAIPEI_RE = re.compile(r"台北|臺北|北市|信義|大安|中山|松山|內湖|南港|文山|士林|北投|萬華|中正|大同")
_RENT_TYPE_RE = re.compile(r"整層|獨立套|獨套|套房")

MAX_PAGES = 5
PAGE_SIZE = 30


class CrawlerDcard(BaseCrawler):
    SOURCE = "dcard"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self.session.headers.update({
            "Referer": "https://www.dcard.tw/f/rent",
            "Origin": "https://www.dcard.tw",
        })

    def crawl(self) -> Iterator[dict]:
        before: int | None = None
        pages = 0

        while pages < MAX_PAGES:
            params: dict = {"limit": PAGE_SIZE}
            if before:
                params["before"] = before

            try:
                resp = self.get(_API_URL, params=params)
                items: list[dict] = resp.json()
            except Exception as exc:
                logger.error("Dcard API error: %s", exc)
                break

            if not items:
                break

            for item in items:
                title = item.get("title", "")
                excerpt = item.get("excerpt", "")
                text = f"{title} {excerpt}"

                if not _TAIPEI_RE.search(text):
                    continue
                if not _RENT_TYPE_RE.search(text):
                    continue

                yield {
                    "id": str(item.get("id", "")),
                    "title": title,
                    "excerpt": excerpt,
                    "content": "",           # full content not fetched at list stage
                    "topics": [t.get("name", "") for t in item.get("topics", [])],
                    "district": "",
                }

            before = items[-1].get("id")
            pages += 1

        logger.info("Dcard: fetched %d pages", pages)
