#!/usr/bin/env python3
"""
Pull Goodreads RSS (server-side) and write `_data/bookshelf.yml`.

Fetches every page of each shelf's RSS (`?page=1`, `?page=2`, …) until a page
returns no items — no per-shelf book cap.

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
from pathlib import Path

import requests

GOODREADS_USER_ID = "85262689"
# Safety only: stop if Goodreads keeps returning pages (should not happen).
MAX_RSS_PAGES = 10_000


@dataclass(frozen=True)
class Book:
    title: str
    author: str
    link: str


def fetch_rss_xml(shelf: str, page: int, timeout_s: int) -> str:
    url = (
        f"https://www.goodreads.com/review/list_rss/{GOODREADS_USER_ID}"
        f"?shelf={shelf}&page={page}"
    )
    resp = requests.get(url, timeout=timeout_s, headers={"User-Agent": "Mozilla/5.0"})
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
        author = re.sub(r"^\s+by\s+", "", author, flags=re.IGNORECASE).strip()
        author = re.sub(r"\s+", " ", author).strip()
        return cleaned_title, author

    return title, ""


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
        page_books = parse_rss_page(xml_text)
        if not page_books:
            break
        for b in page_books:
            if b.link and b.link not in seen_links:
                seen_links.add(b.link)
                all_books.append(b)
        page += 1
    if page > MAX_RSS_PAGES:
        print(
            f"warning: stopped at MAX_RSS_PAGES={MAX_RSS_PAGES} for shelf={shelf!r}",
            file=sys.stderr,
        )
    return all_books


def write_bookshelf_yaml(path: Path, shelves_out: dict[str, list[dict[str, str]]]) -> None:
    """Write Jekyll _data YAML using json.dumps for safe quoting (no PyYAML dep)."""
    lines = [
        "# Bookshelf — Jekyll reads this at build time (see books.html).",
        "# Edit by hand, or overwrite from Goodreads with: python3 generate_books.py",
        f"# Last generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "currently_reading:",
    ]
    for b in shelves_out["currently-reading"]:
        lines.append(f"  - title: {json.dumps(b['title'], ensure_ascii=False)}")
        lines.append(f"    author: {json.dumps(b['author'], ensure_ascii=False)}")
        lines.append(f"    url: {json.dumps(b['link'], ensure_ascii=False)}")
    lines.append("")
    lines.append("read:")
    for b in shelves_out["read"]:
        lines.append(f"  - title: {json.dumps(b['title'], ensure_ascii=False)}")
        lines.append(f"    author: {json.dumps(b['author'], ensure_ascii=False)}")
        lines.append(f"    url: {json.dumps(b['link'], ensure_ascii=False)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds per request.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    yaml_path = repo_root / "_data" / "bookshelf.yml"

    shelves_out: dict[str, list[dict[str, str]]] = {}
    for shelf in ["currently-reading", "read"]:
        books = fetch_entire_shelf(shelf, timeout_s=args.timeout)
        shelves_out[shelf] = [{"title": b.title, "author": b.author, "link": b.link} for b in books]
        print(f"  {shelf!r}: {len(books)} book(s) from RSS")

    write_bookshelf_yaml(yaml_path, shelves_out)
    print(f"Wrote {yaml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
