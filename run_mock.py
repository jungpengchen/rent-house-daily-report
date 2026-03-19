"""
Mock pipeline runner — 不需要網路，直接注入假資料跑完整流程。

用法：
    python run_mock.py            # 跑 pipeline，印出報告
    python run_mock.py --notify   # 同上，並實際發送 Telegram 通知
"""

import argparse
import sys
from pathlib import Path

from normalizer import normalize
from filters import apply_filters
from deduplicator import deduplicate
from report_generator import generate_report
from notifier import dispatch

Path("data").mkdir(exist_ok=True)

# ── Mock 原始資料（模擬各爬蟲吐出的 raw dict）────────────────────────────────

MOCK_RAW = [
    # 591 — 通過所有 filter
    ("591", {
        "post_id": "11111111",
        "title": "大安區近忠孝復興站整層住家 空屋",
        "price": "28000",
        "area": "30",
        "room": "2",
        "living": "1",
        "floor_str": "4F/12F",
        "tags": [{"name": "有電梯"}, {"name": "可開伙"}, {"name": "空屋"}],
        "section_name": "大安區",
        "street_name": "復興南路",
        "lat": "25.041730",
        "lng": "121.544273",
    }),
    # PTT — 同一物件，跨平台重複應被 dedup 合併進上面
    ("ptt", {
        "post_id": "M.1234567890.A",
        "title": "大安整層住家出租 租金：28000 30坪 4/12樓 有電梯",
        "body": "大安區復興南路，空屋，可開伙",
        "url": "https://ptt.cc/bbs/R_EstateExchange/M.1234567890.A.html",
        "district": "大安區",
        "street": "復興南路",
    }),
    # 591 — 信義區，拎包入住
    ("591", {
        "post_id": "22222222",
        "title": "信義區市政府站附近套房 拎包入住",
        "price": "22000",
        "area": "21",
        "room": "1",
        "living": "0",
        "floor_str": "5F/8F",
        "tags": [{"name": "有電梯"}, {"name": "拎包入住"}],
        "section_name": "信義區",
        "street_name": "忠孝東路",
        "lat": "25.040710",
        "lng": "121.564955",
    }),
    # 591 — 南港，3 房
    ("591", {
        "post_id": "33333333",
        "title": "南港區近捷運整層三房",
        "price": "35000",
        "area": "42",
        "room": "3",
        "living": "1",
        "floor_str": "7F/14F",
        "tags": [{"name": "有電梯"}, {"name": "可開伙"}],
        "section_name": "南港區",
        "street_name": "南港路",
        "lat": "25.047504",
        "lng": "121.607332",
    }),
    # 591 — 應被 filter 掉：1 樓
    ("591", {
        "post_id": "44444444",
        "title": "大安一樓店面改套房",
        "price": "18000",
        "area": "20",
        "room": "1",
        "living": "0",
        "floor_str": "1F/6F",
        "tags": [],
        "section_name": "大安區",
        "street_name": "和平東路",
        "lat": "25.025",
        "lng": "121.543",
    }),
    # 591 — 應被 filter 掉：頂樓加蓋
    ("591", {
        "post_id": "55555555",
        "title": "頂樓加蓋採光好套房",
        "price": "15000",
        "area": "10",
        "room": "1",
        "living": "0",
        "floor_str": "6F/6F",
        "tags": [],
        "section_name": "大安區",
        "street_name": "師大路",
        "lat": "25.024",
        "lng": "121.530",
    }),
    # 591 — 應被 filter 掉：離捷運太遠（淡水）
    ("591", {
        "post_id": "66666666",
        "title": "淡水河景整層住家",
        "price": "25000",
        "area": "28",
        "room": "2",
        "living": "1",
        "floor_str": "3F/8F",
        "tags": [{"name": "有電梯"}, {"name": "可開伙"}],
        "section_name": "淡水區",
        "street_name": "中正路",
        "lat": "25.170",
        "lng": "121.440",
    }),
]


def _base_cfg() -> dict:
    return {
        "filters": {
            "floor": {
                "exclude_floor_numbers": [1],
                "exclude_keywords": ["頂樓加蓋", "頂加"],
                "elevator_required_from": 3,
            },
        },
        "mrt": {
            "enabled": True,
            "max_distance_meters": 800,
            "relevant_lines": ["bannan_east", "songshan_partial", "wenhu_nanjing"],
        },
        "dedup": {"area_tolerance_ping": 0.5},
        "notification": {
            "telegram": {"enabled": False},
            "email": {"enabled": False},
            "line_notify": {"enabled": False},
        },
    }


def run_mock(notify: bool = False) -> None:
    cfg = _base_cfg()

    # ── 1. Normalise ──────────────────────────────────────────────────────────
    normalised = []
    for source, raw in MOCK_RAW:
        lst = normalize(source, raw)
        if lst:
            normalised.append(lst)
    print(f"✅ Normalised: {len(normalised)} listings")

    # ── 2. Filter ─────────────────────────────────────────────────────────────
    passed = []
    for lst in normalised:
        ok, reasons, notes = apply_filters(lst, cfg)
        if ok:
            passed.append((lst, notes))
        else:
            print(f"  ❌ Filtered [{lst['source']}:{lst['source_id']}] {lst['title'][:20]}… — {'; '.join(reasons)}")
    print(f"✅ After filter: {len(passed)} passed")

    # ── 3. Deduplicate ────────────────────────────────────────────────────────
    passed_listings = [lst for lst, _ in passed]
    notes_map = {id(lst): notes for lst, notes in passed}
    deduped = deduplicate(passed_listings, area_tolerance=0.5)
    deduped_with_notes = [(lst, notes_map.get(id(lst), [])) for lst in deduped]
    print(f"✅ After dedup: {len(deduped_with_notes)} listings")

    # ── 4. Report ─────────────────────────────────────────────────────────────
    report = generate_report(deduped_with_notes)
    print("\n" + "=" * 60)
    print(report)
    print("=" * 60 + "\n")

    # ── 5. Notify (optional) ──────────────────────────────────────────────────
    if notify:
        cfg["notification"]["telegram"]["enabled"] = True
        sent = dispatch(report, cfg)
        print(f"📨 Dispatched to {sent} channel(s)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--notify", action="store_true", help="實際發送 Telegram 通知")
    args = parser.parse_args()
    run_mock(notify=args.notify)
