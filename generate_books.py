#!/usr/bin/env python3
"""
Sync Goodreads into `_data/bookshelf.yml`.

Fetches every page of each shelf's RSS (`?page=1`, `?page=2`, …) until a page
returns no items — no per-shelf book cap.
If RSS is unavailable, use public widgets and verify their book counts against
the public profile. Incomplete widgets fail without changing the saved bookshelf.

Manual editing: edit `_data/bookshelf.yml` directly when you don't want to sync from Goodreads.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import requests

GOODREADS_USER_ID = "85262689"
# Safety only: stop if Goodreads keeps returning pages (should not happen).
MAX_RSS_PAGES = 10_000

# (Goodreads shelf slug, key written to _data/bookshelf.yml) in page order.
SHELVES = [
    ("currently-reading", "currently_reading"),
    ("read", "read"),
    ("did-not-finish", "did_not_finish"),
]


@dataclass(frozen=True)
class Book:
    title: str
    author: str
    link: str


class RssUnavailable(RuntimeError):
    pass


class LinkParser(HTMLParser):
    """Collect link text and its enclosing div classes without executing scripts."""

    def __init__(self):
        super().__init__()
        self.divs = []
        self.links = []
        self.active = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div":
            self.divs.append(attrs.get("class", ""))
        elif tag == "a":
            self.active = [attrs.get("href", ""), "", tuple(self.divs)]

    def handle_data(self, data):
        if self.active is not None:
            self.active[1] += data

    def handle_endtag(self, tag):
        if tag == "div" and self.divs:
            self.divs.pop()
        elif tag == "a" and self.active is not None:
            self.links.append(self.active)
            self.active = None


def fetch_widget_shelves(timeout_s: int) -> dict[str, list[dict[str, str]]]:
    """Use public widgets, verifying completeness against public profile counts."""
    headers = {"User-Agent": "Mozilla/5.0"}
    profile = requests.get(
        f"https://www.goodreads.com/user/show/{GOODREADS_USER_ID}",
        headers=headers, timeout=timeout_s,
    )
    profile.raise_for_status()
    parser = LinkParser()
    parser.feed(profile.text)
    counts = {}
    for href, text, _classes in parser.links:
        shelf = parse_qs(urlsplit(href).query).get("shelf", [None])[0]
        count = re.search(r"\(([\d,]+)\)", text)
        if shelf and count:
            counts[shelf] = int(count.group(1).replace(",", ""))

    result = {}
    for shelf, _key in SHELVES:
        if shelf not in counts:
            raise RuntimeError(f"Cannot verify public book count for shelf {shelf!r}.")
        response = requests.get(
            f"https://www.goodreads.com/review/custom_widget/{GOODREADS_USER_ID}",
            params={"shelf": shelf, "num_books": 100, "widget_id": f"bookshelf_{shelf}",
                    "show_title": 1, "show_author": 1},
            headers=headers, timeout=timeout_s,
        )
        response.raise_for_status()
        match = re.search(r"var\s+widget_code\s*=\s*'((?:\\.|[^'\\])*)'", response.text)
        if not match:
            raise ValueError(f"Unrecognized Goodreads widget for {shelf!r}.")
        html = json.loads('"' + match.group(1).replace("\\'", "'") + '"')
        widget = LinkParser()
        widget.feed(html)
        titles = []
        authors = []
        served_shelves = set()
        for href, text, classes in widget.links:
            if urlsplit(href).path.startswith(f"/review/list/{GOODREADS_USER_ID}"):
                served_shelves.update(parse_qs(urlsplit(href).query).get("shelf", []))
            if any(c.startswith("gr_custom_title_") for c in classes):
                titles.append((text.strip(), href.split("?", 1)[0]))
            if any(c.startswith("gr_custom_author_") for c in classes):
                authors.append(" ".join(text.split()))
        if served_shelves != {shelf}:
            raise RuntimeError(f"Goodreads widget returned the wrong shelf for {shelf!r}.")
        if (len(titles) != counts[shelf] or len(authors) != len(titles)
                or len({link for _, link in titles}) != len(titles)
                or any(not title or not link for title, link in titles)):
            raise RuntimeError(
                f"Incomplete Goodreads widget for {shelf!r}: expected {counts[shelf]} "
                f"books, received {len(titles)} titles and {len(authors)} authors. "
            )
        result[shelf] = [
            {"title": title, "author": author, "link": link}
            for (title, link), author in zip(titles, authors)
        ]
    return result


def fetch_rss_xml(shelf: str, page: int, timeout_s: int) -> str:
    url = (
        f"https://www.goodreads.com/review/list_rss/{GOODREADS_USER_ID}"
        f"?shelf={shelf}&page={page}"
    )
    resp = requests.get(url, timeout=timeout_s, headers={"User-Agent": "Mozilla/5.0"})
    if resp.status_code in (403, 404):
        raise RssUnavailable(
            f"Goodreads RSS is unavailable (HTTP {resp.status_code}, shelf={shelf!r}, "
            f"page={page})."
        )
    resp.raise_for_status()
    return resp.text


def extract_author_and_title(title: str, description: str) -> tuple[str, str]:
    title = (title or "").strip()
    description = description or ""

    author_match = re.search(r"author:\s*([^<\n]+)", description, flags=re.IGNORECASE)
    if author_match:
        author = re.sub(r"\s+", " ", author_match.group(1)).strip()
        by_author_regex = re.compile(rf"\s+by\s+{re.escape(author)}$", flags=re.IGNORECASE)
        cleaned_title = by_author_regex.sub("", title).strip()
        return cleaned_title, author

    by_pat = re.compile(r"\s+by\s+", flags=re.IGNORECASE)
    matches = [m.start() for m in by_pat.finditer(title)]
    if matches:
        last_idx = matches[-1]
        cleaned_title = title[:last_idx].strip()
        author = title[last_idx:].strip()
        author = re.sub(r"^\s*by\s+", "", author, flags=re.IGNORECASE).strip()
        author = re.sub(r"\s+", " ", author).strip()
        return cleaned_title, author

    return title, ""


def shelf_of_feed(xml_text: str) -> str:
    """Shelf name Goodreads says this feed is for, from `Name's bookshelf: <shelf>`."""
    root = ET.fromstring(xml_text)
    channel_title = root.findtext(".//channel/title") or ""
    _, _, shelf = channel_title.partition("bookshelf:")
    return shelf.strip()


def parse_rss_page(xml_text: str) -> list[Book]:
    """All `<item>` elements on this RSS page (one Goodreads `page=`)."""
    root = ET.fromstring(xml_text)
    items = root.findall(".//item")
    books: list[Book] = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = item.findtext("description") or ""
        book_title, author = extract_author_and_title(title, description)
        books.append(Book(title=book_title, author=author, link=link))
    return books


def fetch_entire_shelf(shelf: str, timeout_s: int) -> list[Book]:
    """Follow Goodreads RSS pagination until an empty page; dedupe by review URL."""
    all_books: list[Book] = []
    seen_links: set[str] = set()
    page = 1
    while page <= MAX_RSS_PAGES:
        xml_text = fetch_rss_xml(shelf, page=page, timeout_s=timeout_s)
        # An unknown shelf slug doesn't 404 — Goodreads quietly serves every book
        # instead, so trust the feed's own shelf name over the one we asked for.
        served_shelf = shelf_of_feed(xml_text)
        if served_shelf != shelf:
            raise RuntimeError(
                f"Goodreads served shelf {served_shelf!r} for requested shelf {shelf!r} — "
                f"the shelf was probably renamed or deleted. Fix SHELVES before syncing."
            )
        page_books = parse_rss_page(xml_text)
        if not page_books:
            break
        previous_count = len(all_books)
        for b in page_books:
            if b.link and b.link not in seen_links:
                seen_links.add(b.link)
                all_books.append(b)
        if len(all_books) == previous_count:
            raise RuntimeError(f"Goodreads repeated a page for shelf {shelf!r}; refusing a partial sync.")
        page += 1
    if page > MAX_RSS_PAGES:
        raise RuntimeError(
            f"Reached MAX_RSS_PAGES={MAX_RSS_PAGES} for shelf={shelf!r}; refusing a partial sync."
        )
    return all_books


def write_bookshelf_yaml(path: Path, shelves_out: dict[str, list[dict[str, str]]]) -> None:
    """Write Jekyll _data YAML using json.dumps for safe quoting (no PyYAML dep)."""
    lines = [
        "# Bookshelf — Jekyll reads this at build time (see books.html).",
        "# Edit by hand, or overwrite from Goodreads with: python3 generate_books.py",
        f"# Last generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    for shelf, yaml_key in SHELVES:
        lines.append(f"{yaml_key}:" if shelves_out[shelf] else f"{yaml_key}: []")
        for b in shelves_out[shelf]:
            lines.append(f"  - title: {json.dumps(b['title'], ensure_ascii=False)}")
            lines.append(f"    author: {json.dumps(b['author'], ensure_ascii=False)}")
            lines.append(f"    url: {json.dumps(b['link'], ensure_ascii=False)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds per request.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    yaml_path = repo_root / "_data" / "bookshelf.yml"

    try:
        shelves_out = {}
        try:
            for shelf, _yaml_key in SHELVES:
                books = fetch_entire_shelf(shelf, timeout_s=args.timeout)
                shelves_out[shelf] = [{"title": b.title, "author": b.author, "link": b.link} for b in books]
            source = "RSS"
        except RssUnavailable:
            print("Goodreads RSS unavailable; trying public bookshelf widgets.")
            shelves_out = fetch_widget_shelves(args.timeout)
            source = "Goodreads widgets"
    except (requests.RequestException, RuntimeError, ET.ParseError, OSError, ValueError) as exc:
        print(f"Bookshelf sync failed: {exc}\nExisting bookshelf was not changed.", file=sys.stderr)
        return 1

    for shelf, _yaml_key in SHELVES:
        print(f"  {shelf!r}: {len(shelves_out[shelf])} book(s) from {source}")
    write_bookshelf_yaml(yaml_path, shelves_out)
    print(f"Wrote {yaml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
