"""
Base crawler with shared session management, anti-crawling helpers,
and a standard interface all concrete crawlers must implement.
"""

import time
import random
import logging
from abc import ABC, abstractmethod
from typing import Iterator

import requests
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)

_UA = None


def _get_ua() -> UserAgent:
    global _UA
    if _UA is None:
        try:
            _UA = UserAgent()
        except Exception:
            _UA = None
    return _UA


FALLBACK_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


def random_user_agent() -> str:
    ua = _get_ua()
    try:
        if ua:
            return ua.random
    except Exception:
        pass
    return random.choice(FALLBACK_UAS)


class BaseCrawler(ABC):
    SOURCE: str = ""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        anti = cfg.get("crawlers", {}).get("anti_crawl", {})
        self.min_delay: float = float(anti.get("min_delay_seconds", 1.5))
        self.max_delay: float = float(anti.get("max_delay_seconds", 4.0))
        self.use_random_ua: bool = bool(anti.get("use_random_user_agent", True))
        self.session = self._make_session()

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": random_user_agent() if self.use_random_ua else FALLBACK_UAS[0],
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "application/json, text/html, */*",
        })
        return s

    def _sleep(self) -> None:
        delay = random.uniform(self.min_delay, self.max_delay)
        time.sleep(delay)

    def _rotate_ua(self) -> None:
        if self.use_random_ua:
            self.session.headers["User-Agent"] = random_user_agent()

    def get(self, url: str, **kwargs) -> requests.Response:
        self._rotate_ua()
        self._sleep()
        resp = self.session.get(url, timeout=20, **kwargs)
        resp.raise_for_status()
        return resp

    def post(self, url: str, **kwargs) -> requests.Response:
        self._rotate_ua()
        self._sleep()
        resp = self.session.post(url, timeout=20, **kwargs)
        resp.raise_for_status()
        return resp

    @abstractmethod
    def crawl(self) -> Iterator[dict]:
        """
        Yield raw listing dicts (un-normalised).
        Each dict must contain at minimum enough data for the normaliser.
        """
        raise NotImplementedError
