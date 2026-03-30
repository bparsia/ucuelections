"""
discover.py — Crawl the UCU "Previous elections" index and update sources/election_pages.csv.

Usage:
    uv run python discover.py              # print discovered URLs, no changes
    uv run python discover.py --update     # merge into sources/election_pages.csv

The script fetches all pages of https://www.ucu.org.uk/article/3529/Previous-elections
plus the current elections landing page.  New URLs are added with include=review;
existing rows (matched by URL) are left untouched so manual notes/include flags survive.
"""

import argparse
import csv
import re
import sys
from itertools import groupby
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

INDEX_URL = "https://www.ucu.org.uk/article/3529/Previous-elections"
CURRENT_URL = "https://www.ucu.org.uk/elections"
BASE_URL = "https://www.ucu.org.uk"
CSV_PATH = Path(__file__).parent / "sources" / "election_pages.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; UCUElectionsScraper/1.0; research use)"
    )
}

# Path substrings that suggest a results page
RESULT_PATTERNS = [
    r"elections?[-_]20\d\d",
    r"elections?-in-20\d\d",
    r"elections?[-_]\d{4}-\d{2}",
    r"NEC-elections",
    r"officer-and-national-executive",
    r"trustee.*officer.*NEC",
    r"trustee.*NEC",
    r"general-secretary-election",
    r"casual.vacancy",
    r"UCU-UK-elections",
    r"ucuscotland-elections",
    r"ucus-elections",
    r"Scotland-elections",
    r"ucuselections",
    r"GS-election",
    r"NECcasualvacancy",
]

# Paths to skip even if they match above
EXCLUDE_PATTERNS = [
    r"About-UCU-elections",
    r"Voting-in-UCUs",
    r"NEC-Elections---Geographical",
    r"election-hustings",
]

RESULT_RE = re.compile("|".join(RESULT_PATTERNS), re.IGNORECASE)
EXCLUDE_RE = re.compile("|".join(EXCLUDE_PATTERNS), re.IGNORECASE)


def fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "lxml")


def extract_links(soup: BeautifulSoup) -> list[dict]:
    found = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(BASE_URL, href) if href.startswith("/") else href
        if "ucu.org.uk" not in urlparse(full).netloc:
            continue
        path = urlparse(full).path
        if RESULT_RE.search(path) and not EXCLUDE_RE.search(path):
            found.append({"url": full.split("?")[0], "anchor": a.get_text(strip=True)})
    return found


def guess_year(url: str, anchor: str) -> str:
    combined = url + " " + anchor
    m = re.search(r"(20\d\d[-/]\d{2})", combined)
    if m:
        return m.group(1).replace("/", "-")
    m = re.search(r"(20\d\d)", combined)
    if m:
        return m.group(1)
    return ""


def guess_type(url: str, anchor: str) -> str:
    text = (url + " " + anchor).lower()
    if "scotland" in text:
        return "Scotland"
    if "general-secretary" in text or "gs-election" in text:
        return "general secretary"
    if "casual" in text:
        return "casual vacancy"
    return "UK national"


def discover_all() -> list[dict]:
    seen: set[str] = set()
    results: list[dict] = []

    def add(links):
        for link in links:
            url = link["url"]
            if url not in seen:
                seen.add(url)
                results.append({
                    "url": url,
                    "anchor": link["anchor"],
                    "year": guess_year(url, link["anchor"]),
                    "election_type": guess_type(url, link["anchor"]),
                })

    print(f"Fetching {CURRENT_URL} ...", file=sys.stderr)
    add(extract_links(fetch(CURRENT_URL)))

    page = 1
    while True:
        url = f"{INDEX_URL}?p={page}&ps=10"
        print(f"Fetching {url} ...", file=sys.stderr)
        soup = fetch(url)
        links = extract_links(soup)
        before = len(seen)
        add(links)
        if not links or len(seen) == before:
            break
        page += 1

    return results


def load_csv() -> dict[str, dict]:
    if not CSV_PATH.exists():
        return {}
    with CSV_PATH.open() as f:
        return {row["url"]: row for row in csv.DictReader(f)}


def save_csv(rows: list[dict]) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["year", "url", "election_type", "notes", "include"]
    with CSV_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def sort_rows(rows: list[dict]) -> list[dict]:
    type_order = {"UK national": 0, "general secretary": 1, "casual vacancy": 2, "Scotland": 3}
    final = []
    grouped = groupby(
        sorted(rows, key=lambda r: type_order.get(r["election_type"], 9)),
        key=lambda r: r["election_type"],
    )
    for _, group in grouped:
        final.extend(sorted(group, key=lambda r: r["year"], reverse=True))
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true",
                        help="Merge discovered URLs into sources/election_pages.csv")
    args = parser.parse_args()

    discovered = discover_all()

    if not args.update:
        print(f"\nDiscovered {len(discovered)} election pages:\n")
        for d in sorted(discovered, key=lambda x: x["year"], reverse=True):
            print(f"  {d['year']:10s}  {d['election_type']:20s}  {d['url']}")
        print("\nRun with --update to merge into sources/election_pages.csv", file=sys.stderr)
        return

    existing = load_csv()
    new_count = 0
    for d in discovered:
        if d["url"] not in existing:
            existing[d["url"]] = {
                "year": d["year"],
                "url": d["url"],
                "election_type": d["election_type"],
                "notes": "",
                "include": "review",
            }
            new_count += 1

    save_csv(sort_rows(list(existing.values())))
    print(f"Updated {CSV_PATH}: {new_count} new URLs added, {len(existing)} total.")


if __name__ == "__main__":
    main()
