"""
全模組測試。

涵蓋情景：
  normalizer   - 591 / PTT / Dcard 正常解析、邊界值、未知來源
  filters      - 樓層/電梯、頂加關鍵字、地下室、傢俱標注、MRT 距離
  deduplicator - 重複偵測、合併 extra_urls、跨平台、相同平台不合併
  report       - 無物件、單筆、多筆、超長訊息分割確認
  database     - init / upsert 新增 / upsert 更新 / record_daily_run
  notifier     - Telegram 成功/失敗/未啟用/缺憑證、分割長訊息
  mrt_data     - haversine 計算、nearest_station、is_within_mrt_distance
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Make sure project root is on path when running from tests/ dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_listing(**kwargs) -> dict:
    """Return a minimal passing listing, overridable via kwargs."""
    base = {
        "source": "591",
        "source_id": "123",
        "url": "https://rent.591.com.tw/home/123",
        "title": "測試物件",
        "rent": 25000,
        "area": 25.0,
        "rooms": 2,
        "living_rooms": 1,
        "floor": 2,
        "total_floors": 8,
        "has_elevator": None,
        "can_cook": True,
        "furniture": "unknown",
        "tags": [],
        "district": "信義區",
        "street": "信義路",
        "latitude": 25.041730,   # near 忠孝復興站
        "longitude": 121.544273,
        "raw": {},
        "extra_urls": [],
    }
    base.update(kwargs)
    return base


def _base_cfg() -> dict:
    return {
        "filters": {
            "floor": {
                "exclude_floor_numbers": [0, 1],
                "exclude_keywords": ["頂樓加蓋", "頂加"],
                "elevator_required_from": 3,
            },
            "furniture": {
                "move_in_ready_tags": ["拎包入住"],
                "furnished_keywords": ["附全套家具", "全套家具", "家具齊全"],
                "empty_tags": ["空屋"],
            },
        },
        "mrt": {
            "enabled": True,
            "max_distance_meters": 800,
            "relevant_lines": ["bannan_east", "songshan_partial", "wenhu_nanjing"],
        },
        "notification": {
            "telegram": {
                "enabled": True,
                "bot_token": "fake_token",
                "chat_id": "12345",
            },
            "email": {"enabled": False},
            "line_notify": {"enabled": False},
        },
        "dedup": {"area_tolerance_ping": 0.5},
    }


# =============================================================================
# normalizer
# =============================================================================

class TestNormalizer(unittest.TestCase):

    def setUp(self):
        from normalizer import normalize
        self.normalize = normalize

    # ── 591 ──────────────────────────────────────────────────────────────────

    def test_591_basic(self):
        raw = {
            "post_id": "999",
            "title": "整層住家近捷運",
            "price": "28000",
            "area": "30",
            "room": "2",
            "living": "1",
            "floor_str": "5F/12F",
            "tags": [{"name": "有電梯"}, {"name": "可開伙"}],
            "section_name": "大安區",
            "street_name": "復興南路",
            "lat": "25.04",
            "lng": "121.54",
        }
        r = self.normalize("591", raw)
        self.assertEqual(r["source"], "591")
        self.assertEqual(r["source_id"], "999")
        self.assertEqual(r["rent"], 28000)
        self.assertEqual(r["area"], 30.0)
        self.assertEqual(r["floor"], 5)
        self.assertEqual(r["total_floors"], 12)
        self.assertTrue(r["has_elevator"])
        self.assertTrue(r["can_cook"])
        self.assertEqual(r["district"], "大安區")
        self.assertAlmostEqual(r["latitude"], 25.04)

    def test_591_basement_floor(self):
        raw = {"post_id": "1", "floor_str": "B1/5F", "tags": []}
        r = self.normalize("591", raw)
        self.assertEqual(r["floor"], -1)

    def test_591_move_in_ready_tag(self):
        raw = {"post_id": "2", "tags": [{"name": "拎包入住"}], "title": ""}
        r = self.normalize("591", raw)
        self.assertEqual(r["furniture"], "move_in_ready")

    def test_591_empty_unit_keyword(self):
        raw = {"post_id": "3", "tags": [], "title": "空屋出租"}
        r = self.normalize("591", raw)
        self.assertEqual(r["furniture"], "empty")

    def test_591_missing_price_area(self):
        raw = {"post_id": "4", "tags": []}
        r = self.normalize("591", raw)
        self.assertEqual(r["rent"], 0)
        self.assertEqual(r["area"], 0.0)

    # ── PTT ──────────────────────────────────────────────────────────────────

    def test_ptt_rent_extraction(self):
        raw = {
            "post_id": "ptt_abc",
            "title": "台北出租",
            "body": "租金：22000 面積30坪 3/8樓 有電梯",
        }
        r = self.normalize("ptt", raw)
        self.assertEqual(r["rent"], 22000)
        self.assertEqual(r["area"], 30.0)
        self.assertEqual(r["floor"], 3)
        self.assertEqual(r["total_floors"], 8)
        self.assertTrue(r["has_elevator"])

    def test_ptt_dollar_sign_rent(self):
        raw = {"post_id": "ptt_2", "title": "$26000 大安區整層", "body": ""}
        r = self.normalize("ptt", raw)
        self.assertEqual(r["rent"], 26000)

    def test_ptt_no_floor_info(self):
        raw = {"post_id": "ptt_3", "title": "出租", "body": "無樓層資訊"}
        r = self.normalize("ptt", raw)
        self.assertEqual(r["floor"], 0)

    # ── Dcard ─────────────────────────────────────────────────────────────────

    def test_dcard_basic(self):
        raw = {
            "id": "dcard_1",
            "title": "租屋資訊",
            "excerpt": "租金：18000 20坪 2/5樓",
            "content": "",
            "topics": [],
        }
        r = self.normalize("dcard", raw)
        self.assertEqual(r["source"], "dcard")
        self.assertEqual(r["rent"], 18000)
        self.assertEqual(r["area"], 20.0)
        self.assertEqual(r["floor"], 2)
        self.assertIn("dcard.tw", r["url"])

    def test_dcard_no_rent(self):
        raw = {"id": "dcard_2", "title": "租屋", "excerpt": "", "content": ""}
        r = self.normalize("dcard", raw)
        self.assertEqual(r["rent"], 0)

    # ── Unknown source ────────────────────────────────────────────────────────

    def test_unknown_source_returns_none(self):
        r = self.normalize("housefun", {"id": "1"})
        self.assertIsNone(r)


# =============================================================================
# filters
# =============================================================================

class TestFilters(unittest.TestCase):

    def setUp(self):
        from filters import apply_filters
        self.apply = apply_filters
        self.cfg = _base_cfg()

    # ── Floor / Elevator ──────────────────────────────────────────────────────

    def test_1f_rejected(self):
        lst = _make_listing(floor=1)
        ok, reasons, _ = self.apply(lst, self.cfg)
        self.assertFalse(ok)
        self.assertTrue(any("1 樓" in r for r in reasons))

    def test_basement_rejected(self):
        lst = _make_listing(floor=-1)
        ok, reasons, _ = self.apply(lst, self.cfg)
        self.assertFalse(ok)
        self.assertTrue(any("地下室" in r for r in reasons))

    def test_2f_passes_without_elevator(self):
        lst = _make_listing(floor=2, has_elevator=None)
        ok, _, _ = self.apply(lst, self.cfg)
        self.assertTrue(ok)

    def test_3f_no_elevator_rejected(self):
        lst = _make_listing(floor=3, has_elevator=None)
        ok, reasons, _ = self.apply(lst, self.cfg)
        self.assertFalse(ok)
        self.assertTrue(any("電梯" in r for r in reasons))

    def test_3f_with_elevator_passes(self):
        lst = _make_listing(floor=3, has_elevator=True)
        ok, _, _ = self.apply(lst, self.cfg)
        self.assertTrue(ok)

    def test_floor_unknown_passes(self):
        lst = _make_listing(floor=0, has_elevator=None)
        ok, _, _ = self.apply(lst, self.cfg)
        self.assertTrue(ok)

    # ── Rooftop keywords ──────────────────────────────────────────────────────

    def test_rooftop_keyword_in_title_rejected(self):
        lst = _make_listing(title="頂樓加蓋優質套房", floor=5, has_elevator=True)
        ok, reasons, _ = self.apply(lst, self.cfg)
        self.assertFalse(ok)
        self.assertTrue(any("頂樓加蓋" in r for r in reasons))

    def test_rooftop_keyword_in_tags_rejected(self):
        lst = _make_listing(tags=["頂加"], floor=5, has_elevator=True)
        ok, _, _ = self.apply(lst, self.cfg)
        self.assertFalse(ok)

    # ── Furniture annotation ──────────────────────────────────────────────────

    def test_move_in_ready_adds_warning_note(self):
        lst = _make_listing(furniture="move_in_ready")
        ok, _, notes = self.apply(lst, self.cfg)
        self.assertTrue(ok)
        self.assertTrue(any("拎包入住" in n for n in notes))

    def test_empty_unit_adds_star_note(self):
        lst = _make_listing(furniture="empty")
        ok, _, notes = self.apply(lst, self.cfg)
        self.assertTrue(ok)
        self.assertTrue(any("極佳" in n for n in notes))

    def test_unknown_furniture_adds_star_note(self):
        # filters.py treats "unknown" same as "empty" → ⭐ note
        lst = _make_listing(furniture="unknown")
        ok, _, notes = self.apply(lst, self.cfg)
        self.assertTrue(ok)
        self.assertTrue(any("極佳" in n for n in notes))

    # ── MRT proximity ─────────────────────────────────────────────────────────

    def test_close_to_mrt_passes(self):
        # 忠孝復興站座標，距離 0 m
        lst = _make_listing(latitude=25.041730, longitude=121.544273)
        ok, _, notes = self.apply(lst, self.cfg)
        self.assertTrue(ok)
        self.assertTrue(any("站" in n for n in notes))

    def test_far_from_mrt_rejected(self):
        # 淡水附近，遠離所有設定捷運站
        lst = _make_listing(latitude=25.17, longitude=121.44)
        ok, reasons, _ = self.apply(lst, self.cfg)
        self.assertFalse(ok)
        self.assertTrue(any("捷運" in r for r in reasons))

    def test_no_coordinates_passes_with_note(self):
        lst = _make_listing(latitude=None, longitude=None)
        ok, _, notes = self.apply(lst, self.cfg)
        self.assertTrue(ok)
        self.assertTrue(any("無座標" in n for n in notes))

    def test_mrt_disabled_skips_check(self):
        cfg = _base_cfg()
        cfg["mrt"]["enabled"] = False
        lst = _make_listing(latitude=25.17, longitude=121.44)
        ok, _, _ = self.apply(lst, cfg)
        self.assertTrue(ok)


# =============================================================================
# deduplicator
# =============================================================================

class TestDeduplicator(unittest.TestCase):

    def setUp(self):
        from deduplicator import deduplicate
        self.dedup = deduplicate

    def _twin(self, source: str, source_id: str) -> dict:
        """Same property listed on a different platform."""
        return _make_listing(
            source=source,
            source_id=source_id,
            rent=25000,
            area=25.0,
            floor=2,
            district="信義區",
            street="信義路",
        )

    def test_no_duplicates(self):
        a = _make_listing(source="591", source_id="1", rent=20000)
        b = _make_listing(source="ptt", source_id="2", rent=30000)
        result = self.dedup([a, b])
        self.assertEqual(len(result), 2)

    def test_cross_platform_duplicate_merged(self):
        a = self._twin("591", "AAA")
        b = self._twin("ptt", "BBB")
        result = self.dedup([a, b])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["extra_urls"]), 1)
        self.assertEqual(result[0]["extra_urls"][0]["source"], "ptt")

    def test_same_platform_not_merged(self):
        a = self._twin("591", "AAA")
        b = self._twin("591", "BBB")  # same source but different ID
        result = self.dedup([a, b])
        self.assertEqual(len(result), 2)

    def test_different_rent_not_merged(self):
        a = self._twin("591", "A")
        b = self._twin("ptt", "B")
        b["rent"] = 26000
        result = self.dedup([a, b])
        self.assertEqual(len(result), 2)

    def test_area_outside_tolerance_not_merged(self):
        a = self._twin("591", "A")
        b = self._twin("ptt", "B")
        b["area"] = 26.0  # > 0.5 ping difference
        result = self.dedup([a, b])
        self.assertEqual(len(result), 2)

    def test_area_within_tolerance_merged(self):
        a = self._twin("591", "A")
        b = self._twin("ptt", "B")
        b["area"] = 25.4  # within 0.5 tolerance
        result = self.dedup([a, b])
        self.assertEqual(len(result), 1)

    def test_different_district_not_merged(self):
        a = self._twin("591", "A")
        b = self._twin("ptt", "B")
        b["district"] = "大安區"
        result = self.dedup([a, b])
        self.assertEqual(len(result), 2)

    def test_empty_streets_both_merge(self):
        a = self._twin("591", "A")
        b = self._twin("ptt", "B")
        a["street"] = ""
        b["street"] = ""
        result = self.dedup([a, b])
        self.assertEqual(len(result), 1)

    def test_extra_urls_not_duplicated(self):
        a = self._twin("591", "A")
        b = self._twin("ptt", "B")
        result = self.dedup([a, b, b])   # b appears twice
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["extra_urls"]), 1)


# =============================================================================
# report_generator
# =============================================================================

class TestReportGenerator(unittest.TestCase):

    def setUp(self):
        from report_generator import generate_report
        self.gen = generate_report

    def test_empty_report(self):
        report = self.gen([])
        self.assertIn("無新上架", report)
        self.assertIn("日報", report)

    def test_single_listing(self):
        lst = _make_listing(rent=25000, area=25.0, title="信義大安美宅")
        report = self.gen([(lst, [])])
        self.assertIn("信義大安美宅", report)
        self.assertIn("25,000", report)
        self.assertIn("25.0 坪", report)

    def test_multiple_listings_numbered(self):
        listings = [(_make_listing(source_id=str(i), title=f"物件{i}"), []) for i in range(3)]
        report = self.gen(listings)
        self.assertIn("【1】", report)
        self.assertIn("【2】", report)
        self.assertIn("【3】", report)
        self.assertIn("共 3 筆", report)

    def test_notes_included(self):
        lst = _make_listing()
        notes = ["⚠️ 拎包入住：可能有電視/床墊，需與房東協商撤走"]
        report = self.gen([(lst, notes)])
        self.assertIn("拎包入住", report)

    def test_extra_urls_included(self):
        lst = _make_listing()
        lst["extra_urls"] = [{"source": "ptt", "url": "https://ptt.cc/xxx"}]
        report = self.gen([(lst, [])])
        self.assertIn("ptt", report.lower())

    def test_unknown_rent_shows_label(self):
        lst = _make_listing(rent=0)
        report = self.gen([(lst, [])])
        self.assertIn("租金不明", report)

    def test_unknown_area_shows_label(self):
        lst = _make_listing(area=0.0)
        report = self.gen([(lst, [])])
        self.assertIn("坪數不明", report)

    def test_floor_labels(self):
        # basement
        r1 = self.gen([(_make_listing(floor=-1), [])])
        self.assertIn("地下室", r1)
        # unknown floor
        r2 = self.gen([(_make_listing(floor=0), [])])
        self.assertIn("樓層不明", r2)
        # with elevator
        r3 = self.gen([(_make_listing(floor=5, total_floors=10, has_elevator=True), [])])
        self.assertIn("🛗有電梯", r3)


# =============================================================================
# database
# =============================================================================

class TestDatabase(unittest.TestCase):

    def setUp(self):
        from database import init_db, upsert_listing, is_new_listing, record_daily_run, get_listing
        self.init_db = init_db
        self.upsert = upsert_listing
        self.is_new = is_new_listing
        self.record_run = record_daily_run
        self.get = get_listing
        self.tmp = tempfile.mktemp(suffix=".db")

    def tearDown(self):
        try:
            os.unlink(self.tmp)
        except FileNotFoundError:
            pass

    def test_init_creates_tables(self):
        self.init_db(self.tmp)
        import sqlite3
        with sqlite3.connect(self.tmp) as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        self.assertIn("listings", tables)
        self.assertIn("daily_runs", tables)

    def test_upsert_new_listing_returns_true(self):
        self.init_db(self.tmp)
        lst = _make_listing(source="591", source_id="NEW1")
        self.assertTrue(self.upsert(self.tmp, lst))

    def test_upsert_existing_returns_false(self):
        self.init_db(self.tmp)
        lst = _make_listing(source="591", source_id="DUP1")
        self.upsert(self.tmp, lst)
        self.assertFalse(self.upsert(self.tmp, lst))

    def test_is_new_before_and_after(self):
        self.init_db(self.tmp)
        self.assertTrue(self.is_new(self.tmp, "591", "X1"))
        self.upsert(self.tmp, _make_listing(source="591", source_id="X1"))
        self.assertFalse(self.is_new(self.tmp, "591", "X1"))

    def test_get_listing_roundtrip(self):
        self.init_db(self.tmp)
        lst = _make_listing(source="591", source_id="TRIP", rent=99000)
        self.upsert(self.tmp, lst)
        fetched = self.get(self.tmp, "591", "TRIP")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["rent"], 99000)

    def test_get_nonexistent_returns_none(self):
        self.init_db(self.tmp)
        self.assertIsNone(self.get(self.tmp, "591", "NOPE"))

    def test_record_daily_run(self):
        self.init_db(self.tmp)
        self.record_run(self.tmp, 5)
        import sqlite3
        with sqlite3.connect(self.tmp) as conn:
            row = conn.execute("SELECT sent_count FROM daily_runs").fetchone()
        self.assertEqual(row[0], 5)


# =============================================================================
# notifier
# =============================================================================

class TestNotifier(unittest.TestCase):

    def setUp(self):
        from notifier import send_telegram, dispatch
        self.send_telegram = send_telegram
        self.dispatch = dispatch

    def _cfg(self, enabled=True, token="tok", chat_id="cid"):
        return {
            "notification": {
                "telegram": {"enabled": enabled, "bot_token": token, "chat_id": chat_id},
                "email": {"enabled": False},
                "line_notify": {"enabled": False},
            }
        }

    @patch("notifier.requests.post")
    def test_telegram_success(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        ok = self.send_telegram("Hello", self._cfg())
        self.assertTrue(ok)
        mock_post.assert_called_once()

    @patch("notifier.requests.post")
    def test_telegram_failure_returns_false(self, mock_post):
        mock_post.side_effect = Exception("network error")
        ok = self.send_telegram("Hello", self._cfg())
        self.assertFalse(ok)

    def test_telegram_disabled_returns_false(self):
        ok = self.send_telegram("Hello", self._cfg(enabled=False))
        self.assertFalse(ok)

    def test_telegram_missing_token_returns_false(self):
        ok = self.send_telegram("Hello", self._cfg(token=""))
        self.assertFalse(ok)

    def test_telegram_missing_chat_id_returns_false(self):
        ok = self.send_telegram("Hello", self._cfg(chat_id=""))
        self.assertFalse(ok)

    @patch("notifier.requests.post")
    def test_long_message_split_into_chunks(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        long_msg = "A" * 9000   # > 4096 chars → should split into 3 chunks
        self.send_telegram(long_msg, self._cfg())
        self.assertEqual(mock_post.call_count, 3)

    @patch("notifier.requests.post")
    def test_dispatch_counts_successful_channels(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.raise_for_status = MagicMock()
        cfg = _base_cfg()
        result = self.dispatch("report text", cfg)
        self.assertEqual(result, 1)   # only telegram enabled

    def test_dispatch_all_disabled_returns_zero(self):
        cfg = {
            "notification": {
                "telegram": {"enabled": False},
                "email": {"enabled": False},
                "line_notify": {"enabled": False},
            }
        }
        result = self.dispatch("report", cfg)
        self.assertEqual(result, 0)


# =============================================================================
# mrt_data
# =============================================================================

class TestMrtData(unittest.TestCase):

    def setUp(self):
        from mrt_data import haversine_meters, nearest_station, is_within_mrt_distance
        self.haversine = haversine_meters
        self.nearest = nearest_station
        self.within = is_within_mrt_distance

    def test_haversine_same_point_is_zero(self):
        d = self.haversine(25.04, 121.54, 25.04, 121.54)
        self.assertAlmostEqual(d, 0.0)

    def test_haversine_known_distance(self):
        # 忠孝復興 to 忠孝敦化 ≈ 630 m
        d = self.haversine(25.041730, 121.544273, 25.041413, 121.551194)
        self.assertGreater(d, 500)
        self.assertLess(d, 750)

    def test_nearest_station_at_zhongxiao_fuxing(self):
        name, line, dist = self.nearest(25.041730, 121.544273)
        self.assertEqual(name, "忠孝復興")
        self.assertLess(dist, 10)

    def test_nearest_station_line_filter(self):
        # 松山站 only on songshan_partial
        name, line, dist = self.nearest(25.050134, 121.577280, line_groups=["songshan_partial"])
        self.assertEqual(name, "松山")
        self.assertEqual(line, "songshan_partial")

    def test_within_distance_true(self):
        passes, name, dist = self.within(25.041730, 121.544273, max_meters=800)
        self.assertTrue(passes)
        self.assertLess(dist, 10)

    def test_within_distance_false(self):
        # 淡水 coords — far from all configured stations
        passes, _, dist = self.within(25.17, 121.44, max_meters=800)
        self.assertFalse(passes)
        self.assertGreater(dist, 800)

    def test_within_distance_boundary(self):
        # Point ~300 m from 忠孝復興：passes at 500 m, fails at 100 m
        lat, lon = 25.044, 121.544  # a few hundred meters north
        passes_loose, _, dist = self.within(lat, lon, max_meters=500)
        self.assertTrue(passes_loose)
        passes_tight, _, _ = self.within(lat, lon, max_meters=int(dist) - 1)
        self.assertFalse(passes_tight)


# =============================================================================
# run
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
