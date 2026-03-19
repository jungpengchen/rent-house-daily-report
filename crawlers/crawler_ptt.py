"""
PTT 租屋版 (Rent_apart) crawler.

Scrapes the PTT web interface at https://www.ptt.cc/bbs/Rent_apart/
and returns posts that mention 台北 in the title.

PTT uses an over-18 gate; we bypass it with the standard cookie trick.
"""

import logging
import re
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base_crawler import BaseCrawler

logger = logging.getLogger(__name__)

_BOARD_URL = "https://www.ptt.cc/bbs/Rent_apart/index.html"
_BASE = "https://www.ptt.cc"

# Only keep posts whose title contains these keywords
_TAIPEI_RE = re.compile(r"台北|臺北|北市|信義|大安|中山|松山|內湖|南港|文山|士林|北投|萬華|中正|大同|文山")
_RENT_TYPE_RE = re.compile(r"整層|獨立套|獨套")

# Max pages to fetch per run (each page has ~20 posts)
MAX_PAGES = 5


class CrawlerPTT(BaseCrawler):
    SOURCE = "ptt"

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        # Bypass the over-18 gate
        self.session.cookies.set("over18", "1", domain="www.ptt.cc")

    def _parse_index(self, html: str) -> tuple[list[dict], str | None]:
        """
        Parse an index page.
        Returns (posts, prev_page_url).
        """
        soup = BeautifulSoup(html, "lxml")
        posts: list[dict] = []

        for entry in soup.select("div.r-ent"):
            title_tag = entry.select_one("div.title a")
            if not title_tag:
                continue
            title = title_tag.get_text(strip=True)
            href = title_tag.get("href", "")
            url = urljoin(_BASE, href)
            posts.append({"title": title, "url": url})

        # Find "上頁" (previous page) link
        prev_url = None
        for btn in soup.select("a.btn.wide"):
            if "上頁" in btn.get_text():
                prev_url = urljoin(_BASE, btn["href"])
                break

        return posts, prev_url

    def _fetch_post_body(self, url: str) -> str:
        try:
            resp = self.get(url)
            soup = BeautifulSoup(resp.text, "lxml")
            content = soup.select_one("#main-content")
            if content:
                # Remove metadata spans
                for tag in content.select("div.article-metaline, div.push"):
                    tag.decompose()
                return content.get_text(" ", strip=True)
        except Exception as exc:
            logger.debug("PTT post fetch failed %s: %s", url, exc)
        return ""

    def crawl(self) -> Iterator[dict]:
        try:
            resp = self.get(_BOARD_URL)
        except Exception as exc:
            logger.error("PTT board fetch failed: %s", exc)
            return

        current_url: str | None = _BOARD_URL
        pages_fetched = 0

        while current_url and pages_fetched < MAX_PAGES:
            try:
                resp = self.get(current_url)
            except Exception as exc:
                logger.error("PTT page fetch failed %s: %s", current_url, exc)
                break

            posts, prev_url = self._parse_index(resp.text)
            pages_fetched += 1

            for post in posts:
                title = post["title"]
                # Filter by Taipei keywords and property type
                if not _TAIPEI_RE.search(title):
                    continue
                if not _RENT_TYPE_RE.search(title):
                    continue

                url = post["url"]
                # Derive a stable post_id from URL
                post_id = url.rstrip("/").split("/")[-1].replace(".html", "")

                body = self._fetch_post_body(url)

                yield {
                    "post_id": post_id,
                    "title": title,
                    "url": url,
                    "body": body,
                    "district": "",   # parsed later by normaliser
                    "street": "",
                }

            current_url = prev_url

        logger.info("PTT: fetched %d pages", pages_fetched)
