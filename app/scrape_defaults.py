"""
Default CSS selector configurations for common Indian college/university
website notification patterns.

Each entry is a dict with:
  css         - BeautifulSoup CSS selector string for notification row/item
  title_attr  - Where to pull the notification title:
                "text"  → element.get_text(strip=True)
                "title" → element.get("title", "")
                "alt"   → element.get("alt", "")
  link_tag    - CSS sub-selector within the item to find <a> for the link
                (None → look for first <a> anywhere inside the item)
  context     - Human-readable description of the pattern (for logging)
"""

# fmt: off
DEFAULT_SELECTORS = [
    # ── Pattern 1: Simple list under a notification div ──────────────────────
    {
        "css": ".notification-list li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Generic .notification-list li"
    },
    # ── Pattern 2: NIC-style notice board (used by many govt colleges) ───────
    {
        "css": "#noticeBoard li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "NIC-style #noticeBoard li"
    },
    {
        "css": ".notice-board li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "NIC-style .notice-board li"
    },
    # ── Pattern 3: Marquee ticker lists ──────────────────────────────────────
    {
        "css": ".marque-list li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Marquee ticker .marque-list li"
    },
    {
        "css": ".marquee-content li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Marquee ticker .marquee-content li"
    },
    # ── Pattern 4: Table-based notice boards ─────────────────────────────────
    {
        "css": "table.noticeboard tr",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Table-based noticeboard row"
    },
    {
        "css": "table.notice-table tr",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Table notice-table row"
    },
    {
        "css": ".table-striped tr",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Bootstrap striped table row"
    },
    # ── Pattern 5: WordPress-style news/post lists ────────────────────────────
    {
        "css": "article.post h2.entry-title",
        "title_attr": "text",
        "link_tag": "a",
        "context": "WordPress article h2.entry-title"
    },
    {
        "css": ".news-list .news-item",
        "title_attr": "text",
        "link_tag": "a",
        "context": "News list item"
    },
    # ── Pattern 6: Bootstrap card/panel-based portals ────────────────────────
    {
        "css": ".card-body .list-group-item",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Bootstrap card list-group-item"
    },
    {
        "css": ".panel-body li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Bootstrap panel-body li"
    },
    # ── Pattern 7: University portal specific ────────────────────────────────
    {
        "css": ".latest-news li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Latest news section li"
    },
    {
        "css": ".announcements li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Announcements section li"
    },
    {
        "css": ".whats-new li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Whats-new section li"
    },
    {
        "css": ".recent-updates li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Recent-updates section li"
    },
    # ── Pattern 8: Div-row based layouts ─────────────────────────────────────
    {
        "css": ".notification-item",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Generic .notification-item div"
    },
    {
        "css": ".notice-item",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Generic .notice-item div"
    },
    # ── Pattern 9: Anchor-direct links in a notice area ──────────────────────
    {
        "css": "#notices a",
        "title_attr": "text",
        "link_tag": None,  # The item itself is the link
        "context": "#notices direct anchors"
    },
    {
        "css": ".notice-area a",
        "title_attr": "text",
        "link_tag": None,
        "context": ".notice-area direct anchors"
    },
    # ── Pattern 10: Unordered lists inside a ticker/scroll widget ────────────
    {
        "css": ".ticker-content ul li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Ticker scroll widget li"
    },
    {
        "css": ".scroll-text li",
        "title_attr": "text",
        "link_tag": "a",
        "context": "Scroll-text li"
    },
    # ── Pattern 11: Data-attribute powered lists ──────────────────────────────
    {
        "css": "[data-type='notice']",
        "title_attr": "text",
        "link_tag": "a",
        "context": "data-type=notice items"
    },
]
# fmt: on


def get_default_selectors():
    """Return a copy of the default selector list."""
    return list(DEFAULT_SELECTORS)
