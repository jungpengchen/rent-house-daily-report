"""
Daily report generator.

Takes a list of (listing, notes) tuples and formats them into a
human-readable text/Markdown report for Telegram / Email.
"""

from datetime import date


def _floor_label(listing: dict) -> str:
    floor = listing.get("floor", 0)
    total = listing.get("total_floors", 0)
    elev = listing.get("has_elevator")

    if floor == -1:
        floor_str = "地下室"
    elif floor == 0:
        floor_str = "樓層不明"
    elif total:
        floor_str = f"{floor}F / {total}F"
    else:
        floor_str = f"{floor}F"

    if elev is True:
        floor_str += " 🛗有電梯"
    elif elev is False:
        floor_str += " ❌無電梯"

    return floor_str


def _layout_label(listing: dict) -> str:
    rooms = listing.get("rooms", 0)
    living = listing.get("living_rooms", 0)
    if rooms or living:
        return f"{rooms}房{living}廳"
    return "格局不明"


def _format_listing(index: int, listing: dict, notes: list[str]) -> str:
    """Format a single listing entry."""
    title = listing.get("title", "(無標題)")
    url = listing.get("url", "")
    rent = listing.get("rent", 0)
    area = listing.get("area", 0.0)
    source = listing.get("source", "")
    extra_urls = listing.get("extra_urls", [])

    rent_str = f"{rent:,} 元/月" if rent else "租金不明"
    area_str = f"{area:.1f} 坪" if area else "坪數不明"
    layout = _layout_label(listing)
    floor = _floor_label(listing)

    lines = [
        f"{'─' * 40}",
        f"【{index}】{title}",
        f"🔗 {url}",
        f"💰 {rent_str}　📐 {area_str}　🏠 {layout}",
        f"🏢 {floor}",
    ]

    if notes:
        for note in notes:
            lines.append(f"  {note}")

    if extra_urls:
        also = "  📎 同物件其他平台：" + "、".join(
            f"{u['source']}: {u['url']}" for u in extra_urls
        )
        lines.append(also)

    if source:
        lines.append(f"  來源：{source.upper()}")

    return "\n".join(lines)


def generate_report(listings_with_notes: list[tuple[dict, list[str]]], stats: dict | None = None) -> str:
    """
    Build the full daily report string.

    Args:
        listings_with_notes: list of (listing_dict, notes_list)
        stats: optional pipeline stats for diagnostics

    Returns:
        Formatted report string (Markdown-compatible).
    """
    today = date.today().strftime("%Y-%m-%d")
    count = len(listings_with_notes)

    stats_line = ""
    if stats:
        stats_line = (
            f"\n[診斷] 爬取 {stats.get('crawled', '?')} 筆"
            f" → 過濾後 {stats.get('deduped', '?')} 筆"
            f" → 新物件 {stats.get('new', '?')} 筆"
        )

    if count == 0:
        return (
            f"591 台北租屋日報 {today}\n\n"
            f"今日無新上架符合條件的物件。{stats_line}"
        )

    header = (
        f"591 台北租屋日報 {today}\n"
        f"共 {count} 筆新物件符合條件\n"
        f"搜尋條件：台北市 | 整層住家/獨立套房 | ≤38,000元 | ≥20坪 | 可開伙\n"
    )

    sections = [
        _format_listing(i + 1, listing, notes)
        for i, (listing, notes) in enumerate(listings_with_notes)
    ]

    return header + "\n" + "\n\n".join(sections)
