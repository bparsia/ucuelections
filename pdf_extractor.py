"""
pdf_extractor.py — Extract STV count-sheet data from downloaded scrutineer PDFs.

For each year in sources/election_pages.csv (include=yes), processes every PDF
in data/raw/{dir}/pdfs/ and writes structured contest/candidate/round data to
data/raw/{dir}/pdf_records.json.

A "count sheet" is a PDF containing a single STV table for one contest.
A "scrutineer report" covers multiple contests with summary data only.
Both are processed; count sheets yield full round-by-round STV data while
scrutineer reports yield elected candidates and turnout figures.

Usage:
    uv run python pdf_extractor.py                  # all years
    uv run python pdf_extractor.py --year 2024-25   # single year
    uv run python pdf_extractor.py --year 2024-25 --verbose
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import pdfplumber

CSV_PATH = Path(__file__).parent / "sources" / "election_pages.csv"
DATA_DIR = Path(__file__).parent / "data" / "raw"

# Candidate name flags like [woman], [post-92], [academic related]
DEMOGRAPHIC_RE = re.compile(r"\[([^\]]+)\]")

# Rows to skip in STV tables (checked against lowercased, whitespace-normalised name)
SKIP_ROW_NAMES = {"non-transferable", "non- transferable", "totals", "total", "candidates", ""}

# Name prefixes that indicate a metadata/header row rather than a candidate
SKIP_NAME_PREFIXES = (
    "election for", "date", "quota", "number to be elected",
    "valid votes", "invalid votes", "election rules", "estv",
    "non-transferable", "non- transferable",
    "papers transferred", "vote required", "over quota",
    "votes required", "transfer value",
    "stage ", "surplus of", "with ", "total present",
    "no candidates", "transfer the", "candidate",
)


def _is_junk_name(name: str) -> bool:
    """Return True for PDF artefacts mistaken for candidate names.

    Rotated page labels ('CONFIDENTIAL', '4', 'fo', 'egaP' = 'Page' mirrored)
    appear in some PDFs when pdfplumber extracts sidebar text.
    """
    s = name.strip()
    sl = s.lower()
    if len(s) <= 2:           # single chars and two-char fragments like "fo"
        return True
    if s.isdigit():            # bare page numbers
        return True
    if sl in {"confidential", "egap", "page", "with"}:
        return True
    if "non-transferable" in sl:   # contest-name + "N papers non-transferable"
        return True
    if " elected " in sl or sl.endswith(" elected"):  # stage-detail lines
        return True
    return False

# Metadata field labels in the first rows of count sheets
METADATA_LABELS = {
    "election for": "contest_name",
    "date": "date",
    "number to be elected": "seats",
    "valid votes": "valid_votes",
    "invalid votes": "invalid_votes",
    "quota": "quota",
    "election rules": "election_rules",
    "estv reg. 54096": "estv_version",
}


# ---------------------------------------------------------------------------
# Table detection helpers
# ---------------------------------------------------------------------------

def is_image_pdf(pdf: pdfplumber.PDF) -> bool:
    return all(len(p.chars) == 0 for p in pdf.pages)


def cell(val) -> str:
    """Normalise a table cell: collapse all whitespace (including newlines) to single spaces."""
    if val is None:
        return ""
    return " ".join(str(val).split())


def looks_like_count_sheet(table: list[list]) -> bool:
    """True if the table has an 'Election for' header row."""
    for row in table[:10]:
        if row and cell(row[0]).lower().startswith("election for"):
            return True
    return False


def has_stage_columns(table: list[list]) -> bool:
    """True if the table has STV stage columns."""
    for row in table[:15]:
        if any(cell(c) == "Stage" for c in row):
            return True
    return False


# ---------------------------------------------------------------------------
# Metadata parsing
# ---------------------------------------------------------------------------

def parse_metadata(table: list[list]) -> dict:
    """Extract contest metadata from the first rows of a count-sheet table."""
    meta = {}
    for row in table[:10]:
        if not row:
            continue
        key = cell(row[0]).lower().rstrip(":")
        val = cell(row[1]) if len(row) > 1 else ""
        field = METADATA_LABELS.get(key)
        if field and val:
            if field == "contest_name":
                val = re.sub(r"\s+APPENDIX\s+\w+$", "", val).strip()
            meta[field] = val
    return meta


# ---------------------------------------------------------------------------
# Stage column map
# ---------------------------------------------------------------------------

def build_stage_map(table: list[list]) -> tuple[dict[int, tuple[int, int]], bool, int]:
    """
    Find the stage header rows and return:
      stage_map     – {stage_num: (transfer_col, total_col)}
      has_fp_col    – True if col 1 is first preferences (first page),
                      False for continuation pages
      status_col    – index of the Elected/status column (-1 if unknown)

    On the first page:
        row: ['', '', 'Stage', '2', 'Stage', '3', ...]
        col 1 = first preferences; each stage N has (transfer=2*(N-1), total=2*(N-1)+1)

    On continuation pages:
        row: ['', 'Stage', '9', 'Stage', '10', ...]
        each stage N has (transfer=i, total=i+1) where header[i]=='Stage'
    """
    stage_row = None
    candidates_row = None

    for i, row in enumerate(table):
        if any(cell(c) == "Stage" for c in row):
            stage_row = row
        if row and cell(row[0]).lower() == "candidates":
            candidates_row = row
            break

    if stage_row is None:
        return {}, False, -1

    # Is col 1 'First' / empty → first page; or 'Stage' → continuation?
    col1 = cell(stage_row[1]) if len(stage_row) > 1 else ""
    has_fp_col = col1 in ("", "First")

    stage_map: dict[int, tuple[int, int]] = {}
    for i, c in enumerate(stage_row):
        if cell(c) == "Stage" and i + 1 < len(stage_row):
            num_str = cell(stage_row[i + 1])
            try:
                n = int(num_str)
                stage_map[n] = (i, i + 1)
            except ValueError:
                pass

    # Status column: on a page where some candidates are elected, it's the last
    # non-blank column in the candidates header row (or just len-1).
    status_col = -1
    if candidates_row is not None:
        # Prefer the column after the last stage's total column
        if stage_map:
            last_total = max(v[1] for v in stage_map.values())
            status_col = last_total + 1
        else:
            status_col = len(candidates_row) - 1

    return stage_map, has_fp_col, status_col


# ---------------------------------------------------------------------------
# Candidate row parsing
# ---------------------------------------------------------------------------

def parse_name(raw: str) -> tuple[str, list[str]]:
    """
    Split 'BURKE, Lucy [woman] [post-92]' into
    ('BURKE, Lucy', ['woman', 'post-92'])
    """
    flags = DEMOGRAPHIC_RE.findall(raw)
    name = DEMOGRAPHIC_RE.sub("", raw).strip()
    return name, [f.strip() for f in flags]


def parse_float(s: str) -> float | None:
    s = s.replace(",", "").replace("\n", "").strip()
    if s in ("-", "", "Elected", "Withdrawn"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_single_round(table: list[list]) -> list[dict]:
    """
    Parse a first-preference-only (no STV stages) count sheet.
    Format: [name, first_prefs, status_or_empty, ...]
    """
    candidates = []
    data_start = 0
    for i, row in enumerate(table):
        if row and cell(row[0]).lower() == "candidates":
            data_start = i + 1
            break

    for row in table[data_start:]:
        if not row or not row[0]:
            continue
        name_raw = cell(row[0])
        name_lower = name_raw.lower()
        if name_lower in SKIP_ROW_NAMES:
            continue
        if any(name_lower.startswith(p) for p in SKIP_NAME_PREFIXES):
            continue
        if _is_junk_name(name_raw):
            continue

        name, flags = parse_name(name_raw)
        fp_raw = cell(row[1]) if len(row) > 1 else ""

        if fp_raw.lower() == "withdrawn":
            candidates.append({
                "name_raw": name_raw, "name": name,
                "demographic_flags": flags, "outcome": "Withdrawn", "rounds": {},
            })
            continue

        fp = parse_float(fp_raw)
        rounds = {}
        if fp is not None:
            rounds[1] = {"votes": fp, "transfer": None, "eliminated": False}

        # Status: look for 'Elected' anywhere in row cols 2+
        outcome = "Not Elected"
        for c in row[2:]:
            if cell(c) == "Elected":
                outcome = "Elected"
                break

        candidates.append({
            "name_raw": name_raw, "name": name,
            "demographic_flags": flags, "outcome": outcome, "rounds": rounds,
        })

    return candidates


def parse_candidate_rows(
    table: list[list],
    stage_map: dict[int, tuple[int, int]],
    has_fp_col: bool,
    status_col: int,
) -> list[dict]:
    """
    Parse data rows below the 'Candidates' header into a list of candidate dicts.
    Each dict has: name_raw, name, demographic_flags, outcome, withdrawn, rounds.
    rounds is {stage_num: {'votes': float|None, 'transfer': float|None, 'eliminated': bool}}
    """
    # Find start of data rows
    data_start = 0
    for i, row in enumerate(table):
        if row and cell(row[0]).lower() == "candidates":
            data_start = i + 1
            break

    candidates = []
    for row in table[data_start:]:
        if not row or not row[0]:
            continue
        name_raw = cell(row[0])
        name_lower = name_raw.lower()
        if name_lower in SKIP_ROW_NAMES:
            continue
        if any(name_lower.startswith(p) for p in SKIP_NAME_PREFIXES):
            continue
        if _is_junk_name(name_raw):
            continue
        # Skip rows that look like sub-headers (Stage / Exclusion of …)
        if name_raw in ("", "Stage") or name_lower.startswith("exclusion") or name_lower.startswith("surplus"):
            continue

        name, flags = parse_name(name_raw)

        fp_raw = cell(row[1]) if len(row) > 1 else ""

        # Withdrawn candidates
        if fp_raw.lower() in ("withdrawn", "withdraw"):
            candidates.append({
                "name_raw": name_raw,
                "name": name,
                "demographic_flags": flags,
                "outcome": "Withdrawn",
                "rounds": {},
            })
            continue

        rounds: dict[int, dict] = {}

        # Stage 1 — first preferences (only on first pages)
        if has_fp_col and fp_raw:
            fp = parse_float(fp_raw)
            if fp is not None:
                rounds[1] = {"votes": fp, "transfer": None, "eliminated": False}

        # Subsequent stages
        for stage_num, (tcol, vcol) in stage_map.items():
            total_raw = cell(row[vcol]) if vcol < len(row) else ""
            trans_raw = cell(row[tcol]) if tcol < len(row) else ""

            if total_raw == "-":
                rounds[stage_num] = {"votes": None, "transfer": None, "eliminated": True}
            elif total_raw:
                rounds[stage_num] = {
                    "votes": parse_float(total_raw),
                    "transfer": parse_float(trans_raw),
                    "eliminated": False,
                }

        # Status
        outcome = "Not Elected"
        if status_col >= 0 and status_col < len(row):
            s = cell(row[status_col])
            if s == "Elected":
                outcome = "Elected"
            elif not s and status_col + 1 < len(row) and cell(row[status_col + 1]) == "Elected":
                # Sometimes status is one column later
                outcome = "Elected"

        candidates.append({
            "name_raw": name_raw,
            "name": name,
            "demographic_flags": flags,
            "outcome": outcome,
            "rounds": rounds,
        })

    return candidates


# ---------------------------------------------------------------------------
# Multi-page merge
# ---------------------------------------------------------------------------

def merge_candidate_pages(pages: list[list[dict]]) -> list[dict]:
    """
    Merge candidate data across pages. Each page provides stage data for
    a subset of rounds; combine by candidate name.
    """
    merged: dict[str, dict] = {}

    for page_candidates in pages:
        for c in page_candidates:
            key = c["name"]
            if key not in merged:
                merged[key] = {
                    "name_raw": c["name_raw"],
                    "name": c["name"],
                    "demographic_flags": c["demographic_flags"],
                    "outcome": c["outcome"],
                    "rounds": {},
                }
            # Merge rounds (later pages may override status)
            merged[key]["rounds"].update(c["rounds"])
            if c["outcome"] in ("Elected", "Withdrawn"):
                merged[key]["outcome"] = c["outcome"]

    return list(merged.values())


# ---------------------------------------------------------------------------
# ROV (Report of Vote) parser — 2023-24, 2024-25, 2025-26 summary format
# ---------------------------------------------------------------------------

def is_rov_format(tables: list[list[list]]) -> bool:
    """
    Detect the ROV summary format: first table is a single-column merged text block
    containing 'to elect' or 'ELECTED', with no 'Election for' metadata row.
    """
    if not tables:
        return False
    t = tables[0]
    if not t or not t[0]:
        return False
    text = cell(t[0][0])
    return ("to elect" in text or "ELECTED" in text) and "Election for" not in text


def parse_rov_pdf(path: Path, verbose: bool = False) -> list[dict]:
    """
    Parse a ROV-format scrutineer report.
    Extracts elected candidates and turnout per contest.
    No STV round data is available in this format.
    """
    contests: list[dict] = []

    try:
        with pdfplumber.open(path) as pdf:
            if is_image_pdf(pdf):
                return []

            full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            contest_blocks = _split_rov_text_blocks(full_text)

            for block in contest_blocks:
                candidates = [
                    {
                        "name_raw": n,
                        "name": n,
                        "demographic_flags": DEMOGRAPHIC_RE.findall(n),
                        "outcome": "Elected",
                        "rounds": {},
                    }
                    for n in block.get("elected_names", [])
                ]
                contests.append({
                    "contest_name": block.get("name", ""),
                    "seats": block.get("seats"),
                    "valid_votes": block.get("valid_votes"),
                    "invalid_votes": block.get("invalid_votes"),
                    "date": None,
                    "quota": None,
                    "election_rules": "STV",
                    "source_pdf": str(path.relative_to(Path(__file__).parent)),
                    "source_format": "rov",
                    "candidates": candidates,
                })

    except Exception as e:
        if verbose:
            print(f"    [error] {path.name}: {e}", file=sys.stderr)

    return contests


def _split_rov_text_blocks(text: str) -> list[dict]:
    """
    Split full page text into per-contest blocks using 'CONTEST:' markers.
    Skips the document header (everything before the first CONTEST:).
    Returns list of dicts with name, seats, valid_votes, invalid_votes, elected_names.
    """
    text = re.sub(r"\n+", "\n", text)

    # Split on CONTEST: — first element is the document header, skip it
    parts = re.split(r"CONTEST:", text)
    blocks = []

    for part in parts[1:]:  # skip header
        if not part.strip():
            continue
        lines = [l.strip() for l in part.splitlines() if l.strip()]
        if not lines:
            continue

        name = lines[0].strip()
        seats = None
        valid_votes = None
        invalid_votes = None
        elected_names: list[str] = []
        in_elected = False

        for line in lines[1:]:
            m = re.search(r"(\d+)\s+to\s+elect", line, re.IGNORECASE)
            if m:
                seats = int(m.group(1))
            m = re.search(r"Total number of valid votes to be counted[:\s]+([0-9,]+)", line, re.IGNORECASE)
            if m:
                valid_votes = int(m.group(1).replace(",", ""))
            m = re.search(r"Number of votes found to be invalid[:\s]+([0-9,]+)", line, re.IGNORECASE)
            if m:
                invalid_votes = int(m.group(1).replace(",", ""))

            # Collect elected names
            if line == "ELECTED":
                in_elected = True
                continue
            if in_elected:
                # Stop collecting when we hit stats or keywords
                if re.match(r"(Number of|Votes cast|Total number|Turnout|The following|The election)", line):
                    in_elected = False
                elif not _is_junk_name(line):
                    elected_names.append(line)

        blocks.append({
            "name": name,
            "seats": seats,
            "valid_votes": valid_votes,
            "invalid_votes": invalid_votes,
            "elected_names": elected_names,
        })

    return blocks


# ---------------------------------------------------------------------------
# Full PDF parser
# ---------------------------------------------------------------------------

def parse_count_sheet_pdf(path: Path, verbose: bool = False) -> list[dict]:
    """
    Parse a count-sheet PDF. Returns a list of contest records.
    Most PDFs contain exactly one contest; some (large scrutineer reports) have several.
    """
    contests: list[dict] = []
    current_meta: dict = {}
    page_candidates: list[list[dict]] = []

    try:
        with pdfplumber.open(path) as pdf:
            if is_image_pdf(pdf):
                if verbose:
                    print(f"    [skip] image-only PDF: {path.name}")
                return []

            # Detect ROV summary format before full parse
            first_page_tables = pdf.pages[0].extract_tables() if pdf.pages else []
            if is_rov_format(first_page_tables):
                if verbose:
                    print(f"    [rov] {path.name}")
                return parse_rov_pdf(path, verbose=verbose)

            for page_num, page in enumerate(pdf.pages):
                tables = page.extract_tables()
                if not tables:
                    # Try to extract text for 2007-style fixed-width PDFs
                    if page_num == 0:
                        text = page.extract_text() or ""
                        text_result = parse_text_page(text, str(path.relative_to(Path(__file__).parent)))
                        if text_result:
                            contests.append(text_result)
                    continue

                for table in tables:
                    if not table or len(table) < 3:
                        continue

                    # New contest starts with 'Election for' metadata
                    if looks_like_count_sheet(table):
                        # Save previous contest if any
                        if current_meta and page_candidates:
                            all_candidates = merge_candidate_pages(page_candidates)
                            if all_candidates:
                                contests.append({**current_meta, "candidates": all_candidates, "source_pdf": str(path.relative_to(Path(__file__).parent))})
                        current_meta = parse_metadata(table)
                        page_candidates = []

                    if not has_stage_columns(table):
                        # Single-round contest (FPTP or uncontested STV)
                        cands = parse_single_round(table)
                        if cands:
                            page_candidates.append(cands)
                        continue

                    stage_map, has_fp, status_col = build_stage_map(table)
                    if not stage_map:
                        continue

                    cands = parse_candidate_rows(table, stage_map, has_fp, status_col)
                    if cands:
                        page_candidates.append(cands)

            # Flush last contest
            if current_meta and page_candidates:
                all_candidates = merge_candidate_pages(page_candidates)
                if all_candidates:
                    contests.append({**current_meta, "candidates": all_candidates, "source_pdf": str(path.relative_to(Path(__file__).parent))})

    except Exception as e:
        if verbose:
            print(f"    [error] {path.name}: {e}", file=sys.stderr)

    return contests


# ---------------------------------------------------------------------------
# 2007 text-based parser
# ---------------------------------------------------------------------------

def parse_text_page(text: str, source: str) -> dict | None:
    """
    Parse a 2007-era fixed-width text page (no tables).
    Returns a minimal contest record or None.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None

    # Look for 'Election for' line
    contest_name = None
    for line in lines:
        m = re.match(r"Election for\s+(.+)", line, re.IGNORECASE)
        if m:
            contest_name = re.sub(r"\s+APPENDIX\s+\w+$", "", m.group(1).strip())
            break

    if not contest_name:
        return None

    meta: dict = {"contest_name": contest_name, "source_pdf": source, "source_format": "text"}

    for line in lines:
        for label, field in METADATA_LABELS.items():
            if line.lower().startswith(label):
                val = line[len(label):].strip()
                # contest_name already set (with APPENDIX stripped); don't overwrite
                if field != "contest_name":
                    meta[field] = val
                break

    # Find 'Candidates' line and parse the data rows
    # Format: NAME  first_pref  stage2_transfer  stage2_total ...
    candidates: list[dict] = []
    in_data = False
    header_stages: list[int] = []

    for line in lines:
        if line.lower().startswith("candidates"):
            in_data = True
            continue
        if not in_data:
            # Collect stage numbers from the stage header line
            nums = re.findall(r"\bStage\s+(\d+)", line)
            if nums:
                header_stages = [int(n) for n in nums]
            continue

        # Stop data section at the Totals row (everything after is stage detail)
        if re.match(r"^Totals?\b", line, re.IGNORECASE):
            in_data = False
            continue

        # Skip header rows within the data section
        if re.match(r"^(First|Surplus|Exclusion|Stage|Candidates|Non-transferable|Quota)\b", line, re.IGNORECASE):
            continue

        # Try to parse candidate row: NAME followed by numbers
        parts = line.split()
        if len(parts) < 2:
            continue

        # Find where the numbers start
        num_start = None
        for i, p in enumerate(parts):
            if re.match(r"^-?[\d,.]+$", p) or p in ("Withdrawn", "-"):
                num_start = i
                break

        if num_start is None or num_start == 0:
            continue

        name_raw = " ".join(parts[:num_start])
        name_lower = name_raw.lower()
        if _is_junk_name(name_raw) or any(name_lower.startswith(p) for p in SKIP_NAME_PREFIXES):
            continue
        name, flags = parse_name(name_raw)
        values = parts[num_start:]

        if values[0].lower() == "withdrawn":
            candidates.append({
                "name_raw": name_raw, "name": name,
                "demographic_flags": flags, "outcome": "Withdrawn", "rounds": {},
            })
            continue

        rounds: dict[int, dict] = {}
        # First value = first preferences
        fp = parse_float(values[0])
        if fp is not None:
            rounds[1] = {"votes": fp, "transfer": None, "eliminated": False}

        # Subsequent values: alternating (transfer, total) per stage
        stage_idx = 0
        i = 1
        while i + 1 < len(values):
            transfer = parse_float(values[i])
            total_raw = values[i + 1]
            stage_n = header_stages[stage_idx] if stage_idx < len(header_stages) else stage_idx + 2
            if total_raw == "-":
                rounds[stage_n] = {"votes": None, "transfer": None, "eliminated": True}
            elif total_raw:
                rounds[stage_n] = {
                    "votes": parse_float(total_raw),
                    "transfer": transfer,
                    "eliminated": False,
                }
            stage_idx += 1
            i += 2

        outcome = "Elected" if "Elected" in values else "Not Elected"
        candidates.append({
            "name_raw": name_raw, "name": name,
            "demographic_flags": flags, "outcome": outcome, "rounds": rounds,
        })

    if not candidates:
        return None

    meta["candidates"] = candidates
    return meta


# ---------------------------------------------------------------------------
# Ballot-level stats extraction (eligible voters, votes cast, turnout)
# ---------------------------------------------------------------------------

def extract_ballot_stats(path: Path) -> dict | None:
    """
    Extract ballot-level stats from a scrutineer / ROV PDF:
      eligible_voters, votes_cast, turnout_pct, ballot_type.

    ballot_type is inferred from text: 'national', 'HE', 'FE', or 'unknown'.
    Returns None if no stats found.
    """
    try:
        with pdfplumber.open(path) as pdf:
            if is_image_pdf(pdf):
                return None
            text = "\n".join(p.extract_text() or "" for p in pdf.pages[:4])
    except Exception:
        return None

    # Two known field-name variants across years:
    #   Modern (2020+):  "Number of eligible voters" / "Total number of votes cast"
    #   Older (2018-19): "Number of ballot papers distributed" / "Number of ballot papers returned"
    ELIGIBLE_PAT = re.compile(
        r"(?:Number of (?:eligible voters|ballot papers distributed))[\s:]+([0-9,]+)"
    )
    CAST_PAT = re.compile(
        r"(?:Total number of votes cast|Number of ballot papers returned)[\s:]+([0-9,]+)"
    )

    # PDFs with multiple contests each repeat these fields; take the block
    # with the highest eligible_voters (= the full-sector UK Elected Members
    # contest) rather than the first match (which may be a regional contest).
    eligible_matches = [
        (int(m.group(1).replace(",", "")), m.start())
        for m in ELIGIBLE_PAT.finditer(text)
    ]
    if not eligible_matches:
        # Fall back to cast+turnout only
        cast_m    = CAST_PAT.search(text)
        turnout_m = re.search(r"Turnout[\s:]+([0-9.]+)\s*%", text)
        if not (cast_m and turnout_m):
            return None
        cast    = int(cast_m.group(1).replace(",", ""))
        turnout = float(turnout_m.group(1))
        eligible = round(cast / (turnout / 100))
    else:
        eligible, best_pos = max(eligible_matches, key=lambda t: t[0])
        # Find the votes_cast and turnout values that appear *after* this
        # eligible line (i.e. in the same contest block)
        tail = text[best_pos:]
        cast_m    = CAST_PAT.search(tail)
        turnout_m = re.search(r"Turnout[\s:]+([0-9.]+)\s*%", tail)
        cast    = int(cast_m.group(1).replace(",", "")) if cast_m else None
        turnout = float(turnout_m.group(1)) if turnout_m else None

    ballot_type = _infer_ballot_type(text, path.name, eligible)

    return {
        "eligible_voters": eligible,
        "votes_cast": cast,
        "turnout_pct": turnout,
        "ballot_type": ballot_type,
        "source_pdf": str(path.relative_to(Path(__file__).parent)),
    }


def _infer_ballot_type(text: str, filename: str, eligible: int | None) -> str:
    """
    Classify a ballot PDF as 'national', 'HE', 'FE', or 'unknown'.

    Priority:
    1. Filename keywords
    2. Contest names in the text (VP / Trustee → national; HE NEC → HE; FE NEC → FE)
    3. Electorate size (>80k → national)
    """
    fname = filename.lower()
    text_lower = text.lower()

    # Filename signals
    if any(k in fname for k in ("national", "_nat", "nat_", "officer", "trustee",
                                 "vice_pres", "vice-pres", "vp_", "_vp", "rov_1",
                                 "women_he", "women_fe", "black", "disabled",
                                 "lgbt", "migrant", "casual_emp")):
        # Could be national or a specific equality seat — check further
        pass
    if re.search(r"(^|[_\-])fe([_\-]|$)", fname):
        return "FE"
    if re.search(r"(^|[_\-])he([_\-]|$)", fname):
        return "HE"
    if "fe_" in fname or "_fe" in fname or "further_ed" in fname:
        return "FE"
    if "he_" in fname or "_he" in fname or "higher_ed" in fname:
        return "HE"

    # Text: VP / Trustee → national; regional HE/FE NEC → HE or FE
    national_signals = ("vice-president", "vice president", "trustee", "honorary treasurer",
                        "general secretary", "president of ucu", "officers and national",
                        "national executive committee elections")
    if any(s in text_lower for s in national_signals):
        return "national"

    he_signals = ("higher education sector", "he nec", "he uk", "he seats",
                   "he members", "higher education seats")
    fe_signals = ("further education sector", "fe nec", "fe uk", "fe seats",
                   "fe members", "further education seats")
    he_count = sum(text_lower.count(s) for s in he_signals)
    fe_count = sum(text_lower.count(s) for s in fe_signals)
    if he_count > fe_count:
        return "HE"
    if fe_count > he_count:
        return "FE"

    # Electorate size fallback
    if eligible and eligible > 80_000:
        return "national"
    if eligible and eligible < 20_000:
        return "FE"  # FE is typically smaller than HE

    return "unknown"


# ---------------------------------------------------------------------------
# Per-directory orchestration
# ---------------------------------------------------------------------------

def process_dir(raw_dir: Path, verbose: bool = False) -> tuple[list[dict], list[dict]]:
    """
    Process all PDFs in raw_dir/pdfs/.
    Returns (contest_records, ballot_stats_records).
    """
    pdf_dir = raw_dir / "pdfs"
    if not pdf_dir.exists():
        return [], []

    manifest_path = pdf_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        for entry in json.loads(manifest_path.read_text()):
            manifest[entry["filename"]] = entry

    all_contests: list[dict] = []
    all_ballot_stats: list[dict] = []

    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        anchor = manifest.get(pdf_path.name, {}).get("anchor", "")
        if verbose:
            print(f"  [pdf] {pdf_path.name} ({anchor})")

        contests = parse_count_sheet_pdf(pdf_path, verbose=verbose)

        if verbose:
            for c in contests:
                n_cands = len(c.get("candidates", []))
                n_rounds = max((len(cand["rounds"]) for cand in c.get("candidates", [])), default=0)
                print(f"       → {c.get('contest_name', '?')!r:50s} {n_cands} candidates, {n_rounds} rounds")

        all_contests.extend(contests)

        # Ballot stats (only from scrutineer/ROV summary PDFs, not individual count sheets)
        stats = extract_ballot_stats(pdf_path)
        if stats:
            all_ballot_stats.append(stats)

    return all_contests, all_ballot_stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def dir_name(row: dict) -> str:
    suffixes = {"Scotland": "scotland", "general secretary": "gs", "casual vacancy": "cv"}
    year = row["year"] or "unknown"
    suffix = suffixes.get(row.get("election_type", ""))
    return f"{year}_{suffix}" if suffix else year


def load_pages(year_filter: str | None) -> list[dict]:
    with CSV_PATH.open() as f:
        rows = [r for r in csv.DictReader(f) if r["include"] == "yes"]
    if year_filter:
        rows = [r for r in rows if r["year"] == year_filter]
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", help="Only process a specific year")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    pages = load_pages(args.year)
    if not pages:
        print("No matching pages found.", file=sys.stderr)
        sys.exit(1)

    # Deduplicate directories (multiple rows can share a dir for same-year pages)
    seen_dirs: set[str] = set()
    dirs_to_process = []
    for row in pages:
        d = dir_name(row)
        if d not in seen_dirs:
            seen_dirs.add(d)
            dirs_to_process.append((d, row["year"]))

    total_contests = 0

    for dname, year in dirs_to_process:
        raw_dir = DATA_DIR / dname
        if not raw_dir.exists():
            print(f"[{dname}] directory not found — run fetch.py first", file=sys.stderr)
            continue

        print(f"[{dname}]")
        contests, ballot_stats = process_dir(raw_dir, verbose=args.verbose)

        out_path = raw_dir / "pdf_records.json"
        out_path.write_text(json.dumps(contests, indent=2), encoding="utf-8")
        print(f"  → {len(contests)} contest(s) written to {out_path.relative_to(Path(__file__).parent)}")

        stats_path = raw_dir / "ballot_stats.json"
        stats_path.write_text(json.dumps(ballot_stats, indent=2), encoding="utf-8")
        if ballot_stats:
            print(f"  → {len(ballot_stats)} ballot stat(s) written to {stats_path.relative_to(Path(__file__).parent)}")

        total_contests += len(contests)

    print(f"\nTotal: {total_contests} contests across {len(dirs_to_process)} directories.")


if __name__ == "__main__":
    main()
