"""
fetch.py — Download HTML, PDFs, and Word docs for each election page in sources/election_pages.csv.

For each include=yes row:
  - Saves page HTML to data/raw/{year}/page.html
  - Downloads scrutineer report PDFs and count-sheet Word docs to data/raw/{year}/pdfs/
  - Saves a manifest to data/raw/{year}/pdfs/manifest.json (includes filetype field)
  - Extracts uncontested/no-nomination entries to data/raw/{year}/html_records.json

Usage:
    uv run python fetch.py                  # fetch all include=yes pages
    uv run python fetch.py --year 2024-25   # fetch a specific year
    uv run python fetch.py --refresh        # re-download even if already cached
"""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.ucu.org.uk"
CSV_PATH = Path(__file__).parent / "sources" / "election_pages.csv"
DATA_DIR = Path(__file__).parent / "data" / "raw"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; UCUElectionsScraper/1.0; research use)"
    )
}

# Anchor text patterns that identify scrutineer reports / count sheets
SCRUTINEER_PATTERNS = re.compile(
    r"(national|HE|FE|higher education|further education|"
    r"scrutineer|result|report|seats|officer|trustee|count)",
    re.IGNORECASE,
)

# Anchor text patterns for documents we don't want
EXCLUDE_ANCHOR_PATTERNS = re.compile(
    r"(nomination|calling notice|guidance|role outline|"
    r"signature sheet|election address|rules|form|"
    r"hustings|candidate statement|regulations)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp


def get_body(soup: BeautifulSoup) -> BeautifulSoup | None:
    """Return the main article content div."""
    return soup.find("div", class_="bodytext") or soup.find("div", class_="textblock")


# ---------------------------------------------------------------------------
# PDF link extraction
# ---------------------------------------------------------------------------

def find_scrutineer_pdfs(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """
    Return all result/scrutineer PDF links from the page.
    Scans every /media/*.pdf link on the whole page, keeping those whose
    anchor text matches SCRUTINEER_PATTERNS and not EXCLUDE_ANCHOR_PATTERNS.
    """
    candidates: list[dict] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not (href.endswith(".pdf") or "/pdf/" in href):
            continue
        anchor = a.get_text(strip=True)
        if SCRUTINEER_PATTERNS.search(anchor) and not EXCLUDE_ANCHOR_PATTERNS.search(anchor):
            candidates.append({"anchor": anchor, "href": href})

    # Resolve to full URLs and deduplicate
    seen: set[str] = set()
    results: list[dict] = []
    for c in candidates:
        full_url = urljoin(BASE_URL, c["href"]) if c["href"].startswith("/") else c["href"]
        if full_url not in seen:
            seen.add(full_url)
            filename = Path(urlparse(full_url).path).name
            results.append({
                "url": full_url,
                "anchor": c["anchor"],
                "filename": filename,
            })
    return results


# ---------------------------------------------------------------------------
# Word doc link extraction (2011, 2015 count sheets are .doc files)
# ---------------------------------------------------------------------------

def find_count_docs(soup: BeautifulSoup, page_url: str) -> list[dict]:
    """
    Return all count-sheet Word doc links from the page.
    Mirrors find_scrutineer_pdfs but for .doc / .docx hrefs.
    """
    candidates: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not (href.endswith(".doc") or href.endswith(".docx") or "/doc/" in href):
            continue
        anchor = a.get_text(strip=True)
        if SCRUTINEER_PATTERNS.search(anchor) and not EXCLUDE_ANCHOR_PATTERNS.search(anchor):
            candidates.append({"anchor": anchor, "href": href})

    seen: set[str] = set()
    results: list[dict] = []
    for c in candidates:
        full_url = urljoin(BASE_URL, c["href"]) if c["href"].startswith("/") else c["href"]
        if full_url not in seen:
            seen.add(full_url)
            filename = Path(urlparse(full_url).path).name
            results.append({"url": full_url, "anchor": c["anchor"], "filename": filename})
    return results


# ---------------------------------------------------------------------------
# Uncontested / no-nomination extraction
# ---------------------------------------------------------------------------

def extract_html_records(soup: BeautifulSoup, year: str, page_url: str) -> list[dict]:
    """
    Extract uncontested and no-nomination entries from the article HTML.
    These are the only results data we take from the HTML (everything else
    comes from the scrutineer PDFs).

    Uncontested entries look like:
        <p><strong>Midlands HE (3 seats) (uncontested)</strong></p>
        <p><em>Candidate Name (Institution) is declared elected unopposed</em></p>

    No-nomination entries look like:
        <p><strong>Some Seat (1 seat)</strong></p>
        <p>No nominations received.</p>  (or similar phrasing)
    """
    body = get_body(soup)
    if not body:
        return []

    records: list[dict] = []
    elements = list(body.find_all(["h2", "h3", "p"]))

    i = 0
    while i < len(elements):
        el = elements[i]
        text = el.get_text(strip=True)

        # Detect uncontested position heading: <p><strong>... (uncontested)...</strong></p>
        if el.name == "p" and el.find("strong"):
            strong_text = el.get_text(strip=True)
            is_uncontested = bool(re.search(r"\(uncontested\)", strong_text, re.IGNORECASE))
            is_no_nom = bool(re.search(r"no nomination", strong_text, re.IGNORECASE))

            if is_uncontested or is_no_nom:
                position_raw = re.sub(
                    r"\s*\(uncontested\)\s*|\s*\(no nomination[s]?\)\s*",
                    "", strong_text, flags=re.IGNORECASE
                ).strip()
                outcome = "Uncontested" if is_uncontested else "No Nomination"

                # Collect following <em> or plain-text candidate paragraphs
                j = i + 1
                while j < len(elements):
                    next_el = elements[j]
                    next_text = next_el.get_text(strip=True)

                    # Stop at next position heading or section heading
                    if next_el.name in ("h2", "h3"):
                        break
                    if next_el.name == "p" and next_el.find("strong") and next_text:
                        break
                    # Skip empty paragraphs
                    if not next_text:
                        j += 1
                        continue

                    # No-nomination: single paragraph saying "no nominations"
                    if re.search(r"no nomination", next_text, re.IGNORECASE):
                        records.append({
                            "year": year,
                            "position_raw": position_raw,
                            "candidate_name": None,
                            "institution": None,
                            "outcome": "No Nomination",
                            "source": "html",
                            "source_url": page_url,
                        })
                        j += 1
                        break

                    # Uncontested candidate (usually in <em>)
                    if is_uncontested and (next_el.find("em") or outcome == "Uncontested"):
                        candidate_text = next_text
                        # Strip trailing "is declared elected unopposed" etc.
                        candidate_text = re.sub(
                            r"\s*(is declared elected|unopposed|uncontested).*$",
                            "", candidate_text, flags=re.IGNORECASE
                        ).strip()
                        name, institution = parse_candidate(candidate_text)
                        if name:
                            records.append({
                                "year": year,
                                "position_raw": position_raw,
                                "candidate_name": name,
                                "institution": institution,
                                "outcome": "Uncontested",
                                "source": "html",
                                "source_url": page_url,
                            })
                        j += 1
                        continue

                    j += 1
                i = j
                continue

        # Also catch "no nominations received" as a standalone paragraph
        if re.search(r"no nominations? received", text, re.IGNORECASE):
            # Look back for the most recent position heading
            for k in range(i - 1, max(i - 5, -1), -1):
                prev = elements[k]
                if prev.name == "p" and prev.find("strong") and prev.get_text(strip=True):
                    records.append({
                        "year": year,
                        "position_raw": prev.get_text(strip=True),
                        "candidate_name": None,
                        "institution": None,
                        "outcome": "No Nomination",
                        "source": "html",
                        "source_url": page_url,
                    })
                    break

        i += 1

    return records


def parse_candidate(text: str) -> tuple[str | None, str | None]:
    """
    Parse 'Name (she/her) (Institution)' or 'Name - Institution' into (name, institution).
    Returns (None, None) if the text doesn't look like a candidate entry.
    """
    if not text or len(text) < 3:
        return None, None

    # Reject boilerplate / non-candidate lines
    _tl = text.lower()
    if any(phrase in _tl for phrase in (
        "nominations supported", "relevant documents", "at least 10 members",
        "election address", "election rules", "guidance notes",
    )):
        return None, None

    # Strip pronouns like (she/her), (he/him), (they/them)
    text = re.sub(r"\([a-z]+/[a-z]+\)", "", text, flags=re.IGNORECASE).strip()

    # Format: "Name (Institution)" — institution in last parenthesised group
    m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Format: "Name - Institution"
    m = re.match(r"^(.+?)\s+[-–]\s+(.+)$", text)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # Just a name
    return text.strip(), None


# ---------------------------------------------------------------------------
# Per-page orchestration
# ---------------------------------------------------------------------------

def dir_name(row: dict) -> str:
    """Unique directory name for a page: year + type suffix for non-UK-national rows."""
    year = row["year"] or "unknown"
    etype = row.get("election_type", "")
    suffixes = {
        "Scotland": "scotland",
        "general secretary": "gs",
        "casual vacancy": "cv",
    }
    suffix = suffixes.get(etype)
    return f"{year}_{suffix}" if suffix else year


def process_page(row: dict, refresh: bool = False) -> None:
    year = row["year"]
    url = row["url"]
    out_dir = DATA_DIR / dir_name(row)
    pdf_dir = out_dir / "pdfs"
    html_path = out_dir / "page.html"
    manifest_path = pdf_dir / "manifest.json"
    records_path = out_dir / "html_records.json"

    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # --- Fetch HTML ---
    if html_path.exists() and not refresh:
        print(f"  [cache] {html_path}")
        html = html_path.read_text(encoding="utf-8")
    else:
        print(f"  [fetch] {url}")
        resp = fetch_page(url)
        html = resp.text
        html_path.write_text(html, encoding="utf-8")
        time.sleep(1)  # polite crawl delay

    soup = BeautifulSoup(html, "lxml")

    # --- Find and download scrutineer PDFs and count-sheet docs ---
    pdfs = find_scrutineer_pdfs(soup, url)
    docs = find_count_docs(soup, url)
    print(f"  [pdfs]  {len(pdfs)} PDF(s) found")
    print(f"  [docs]  {len(docs)} Word doc(s) found")

    manifest = []
    for item, filetype in [(p, "pdf") for p in pdfs] + [(d, "doc") for d in docs]:
        dest = pdf_dir / item["filename"]
        if dest.exists() and not refresh:
            print(f"    [cache] {item['filename']}")
        else:
            print(f"    [fetch] {item['filename']} ({item['anchor']})")
            resp = fetch_page(item["url"])
            dest.write_bytes(resp.content)
            time.sleep(1)
        manifest.append({
            "url": item["url"],
            "anchor": item["anchor"],
            "filename": item["filename"],
            "filetype": filetype,
            "local_path": str(dest.relative_to(Path(__file__).parent)),
        })

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # --- Extract uncontested / no-nomination entries ---
    records = extract_html_records(soup, year, url)
    print(f"  [html]  {len(records)} uncontested/no-nomination record(s)")
    records_path.write_text(json.dumps(records, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_pages(year_filter: str | None) -> list[dict]:
    with CSV_PATH.open() as f:
        rows = [r for r in csv.DictReader(f) if r["include"] == "yes"]
    if year_filter:
        rows = [r for r in rows if r["year"] == year_filter]
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", help="Only fetch a specific year (e.g. 2024-25)")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-download even if already cached")
    args = parser.parse_args()

    pages = load_pages(args.year)
    if not pages:
        print("No matching pages found in election_pages.csv.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching {len(pages)} election page(s)...\n")
    for row in pages:
        print(f"[{row['year']}] {row['url']}")
        try:
            process_page(row, refresh=args.refresh)
        except Exception as e:
            print(f"  [ERROR] {e}", file=sys.stderr)
        print()

    print("Done.")


if __name__ == "__main__":
    main()
