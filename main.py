"""
Main entry point.

Usage:
    python main.py              # run once immediately
    python main.py --schedule   # run daily at configured hour (default 08:00)
    python main.py --dry-run    # crawl + filter but don't send notifications
                                # (and don't update the DB seen-list)

Environment variables (override config.yaml):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    EMAIL_USERNAME / EMAIL_PASSWORD / EMAIL_TO
    LINE_NOTIFY_TOKEN
    GOOGLE_MAPS_API_KEY
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import yaml
import schedule as sched
from dotenv import load_dotenv

from database import init_db, upsert_listing, record_daily_run
from normalizer import normalize
from filters import apply_filters
from deduplicator import deduplicate
from report_generator import generate_report
from notifier import dispatch
from crawlers.crawler_591 import Crawler591
from crawlers.crawler_ptt import CrawlerPTT
from crawlers.crawler_dcard import CrawlerDcard

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/run.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

_CRAWLER_MAP = {
    "591":   Crawler591,
    "ptt":   CrawlerPTT,
    "dcard": CrawlerDcard,
}


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Core pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(cfg: dict, dry_run: bool = False) -> int:
    """
    Full crawl → normalise → filter → dedup → report → notify pipeline.
    Returns number of new listings sent.
    """
    db_path = cfg.get("database", {}).get("path", "data/listings.db")
    init_db(db_path)

    enabled_sources: list[str] = cfg.get("crawlers", {}).get("enabled", ["591"])

    # ── 1. Crawl all enabled sources ─────────────────────────────────────────
    raw_listings: list[tuple[str, dict]] = []

    for source in enabled_sources:
        crawler_cls = _CRAWLER_MAP.get(source)
        if not crawler_cls:
            logger.warning("No crawler class for source '%s'; skipping.", source)
            continue

        logger.info("Starting crawler: %s", source)
        try:
            crawler = crawler_cls(cfg)
            for raw in crawler.crawl():
                raw_listings.append((source, raw))
        except Exception as exc:
            logger.error("Crawler '%s' crashed: %s", source, exc, exc_info=True)

    logger.info("Crawled %d raw listings total", len(raw_listings))

    # ── 2. Normalise ──────────────────────────────────────────────────────────
    normalised: list[dict] = []
    for source, raw in raw_listings:
        listing = normalize(source, raw)
        if listing:
            normalised.append(listing)

    logger.info("Normalised: %d listings", len(normalised))

    # ── 3. Filter ─────────────────────────────────────────────────────────────
    passed: list[tuple[dict, list[str]]] = []
    rejected = 0
    for listing in normalised:
        ok, reasons, notes = apply_filters(listing, cfg)
        if ok:
            passed.append((listing, notes))
        else:
            rejected += 1
            logger.debug(
                "Filtered out %s:%s — %s",
                listing["source"], listing["source_id"],
                "; ".join(reasons),
            )

    logger.info("After filters: %d passed, %d rejected", len(passed), rejected)

    # ── 4. Deduplicate ────────────────────────────────────────────────────────
    dedup_cfg = cfg.get("dedup", {})
    area_tol = float(dedup_cfg.get("area_tolerance_ping", 0.5))
    passed_listings = [lst for lst, _ in passed]
    notes_map = {id(lst): notes for lst, notes in passed}

    deduped = deduplicate(passed_listings, area_tolerance=area_tol)
    deduped_with_notes = [(lst, notes_map.get(id(lst), [])) for lst in deduped]

    logger.info("After dedup: %d listings", len(deduped_with_notes))

    # ── 5. Keep only NEW listings (not seen before) ───────────────────────────
    new_listings: list[tuple[dict, list[str]]] = []
    for listing, notes in deduped_with_notes:
        is_new = upsert_listing(db_path, listing) if not dry_run else True
        if is_new:
            new_listings.append((listing, notes))

    logger.info("New listings (not seen before): %d", len(new_listings))

    # ── 6. Generate report ────────────────────────────────────────────────────
    stats = {
        "crawled": len(raw_listings),
        "normalised": len(normalised),
        "filtered_out": rejected,
        "deduped": len(deduped_with_notes),
        "new": len(new_listings),
    }
    report = generate_report(new_listings, stats=stats)
    logger.info("Report generated (%d chars)", len(report))

    # Always print to stdout for debugging
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60 + "\n")

    # ── 7. Notify ─────────────────────────────────────────────────────────────
    sent_channels = 0
    if not dry_run:
        sent_channels = dispatch(report, cfg)
        logger.info("Notifications dispatched to %d channel(s)", sent_channels)
    else:
        logger.info("Dry-run: skipping notifications")

    # ── 8. Record run ─────────────────────────────────────────────────────────
    if not dry_run:
        record_daily_run(db_path, len(new_listings))

    return len(new_listings)


# ── Scheduler ─────────────────────────────────────────────────────────────────

def scheduled_job(cfg: dict) -> None:
    logger.info("Scheduled run starting…")
    try:
        count = run_pipeline(cfg)
        logger.info("Scheduled run complete. New listings: %d", count)
    except Exception as exc:
        logger.error("Scheduled run failed: %s", exc, exc_info=True)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="591 Taipei Rental Daily Report")
    parser.add_argument("--schedule", action="store_true",
                        help="Run as a daily scheduled job")
    parser.add_argument("--dry-run", action="store_true",
                        help="Crawl and filter but don't send notifications or update DB")
    parser.add_argument("--config", default="config.yaml",
                        help="Path to config file (default: config.yaml)")
    args = parser.parse_args()

    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)

    cfg = load_config(args.config)

    if args.schedule:
        run_hour = cfg.get("schedule", {}).get("daily_hour", 8)
        run_minute = cfg.get("schedule", {}).get("daily_minute", 0)
        run_time = f"{run_hour:02d}:{run_minute:02d}"

        logger.info("Scheduler started. Will run daily at %s.", run_time)
        sched.every().day.at(run_time).do(scheduled_job, cfg=cfg)

        # Also run once immediately on startup
        logger.info("Running initial crawl on startup…")
        scheduled_job(cfg)

        while True:
            sched.run_pending()
            time.sleep(30)
    else:
        count = run_pipeline(cfg, dry_run=args.dry_run)
        sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
