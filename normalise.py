"""
normalise.py — Merge extracted data and write flat CSV tables.

Reads:
  data/raw/{dir}/pdf_records.json   — structured contest/candidate/round data
  data/raw/{dir}/html_records.json  — uncontested / no-nomination entries
  sources/position_map.csv          — cross-year position normalisation (optional)

Writes:
  data/processed/contests.csv       — one row per contest
  data/processed/candidates.csv     — one row per candidate per contest
  data/processed/stv_rounds.csv     — one row per candidate per round

Usage:
    uv run python normalise.py
    uv run python normalise.py --verbose
"""

import argparse
import csv
import json
import re
from pathlib import Path

RAW_DIR = Path(__file__).parent / "data" / "raw"
OUT_DIR = Path(__file__).parent / "data" / "processed"
POSITION_MAP_PATH = Path(__file__).parent / "sources" / "position_map.csv"
MANUAL_BALLOTS_PATH = Path(__file__).parent / "sources" / "manual_ballots.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

_PAREN_QUALIFIERS = re.compile(
    r"\(\s*(post-92|post92|AR|HE|FE|academic[\s\-]related|[a-z]+/[a-z]+)\s*\)",
    re.IGNORECASE,
)
_FUSED_SUFFIXES = re.compile(r"-(post-92|post92|AR|HE|FE)\s*$", re.IGNORECASE)
_BRACKET_ANNOT  = re.compile(r"\[.*?\]")
_HONORIFICS     = re.compile(
    r"^(Dr|Prof(?:essor)?|Mr|Mrs|Ms|Miss|Rev(?:d)?|Sir|Lord|Lady|Mx)\.?\s+",
    re.IGNORECASE,
)


def _cap_word(w: str) -> str:
    """Title-case a single word, preserving Mc/Mac/O'/hyphenated compounds."""
    if not w:
        return w
    wu = w.upper()
    if wu.startswith("MC") and len(w) > 2 and w[2:3].isalpha():
        return "Mc" + _cap_word(w[2:])
    if wu.startswith("MAC") and len(w) > 3 and w[3:4].isalpha():
        return "Mac" + _cap_word(w[3:])
    if "'" in w:
        idx = w.index("'")
        return w[:idx].capitalize() + "'" + _cap_word(w[idx + 1:])
    if "-" in w:
        return "-".join(_cap_word(p) for p in w.split("-"))
    return w.capitalize()


def _is_allcaps_token(tok: str) -> bool:
    """True if the token looks like an all-caps surname (e.g. FOWLER, McINTOSH)."""
    core = tok
    for pfx in ("MC", "MAC"):
        if core.upper().startswith(pfx) and len(core) > len(pfx) and core[len(pfx):len(pfx)+1].isalpha():
            core = core[len(pfx):]
            break
    if len(core) >= 2 and core[1:2] == "'" :   # D'ARCY etc — skip prefix char+apostrophe
        core = core[2:]
    core_alpha = re.sub(r"[^A-Za-z]", "", core)
    return len(core_alpha) >= 2 and core_alpha.isupper()


def normalise_name(name: str) -> str:
    """
    Deterministic name normalisation → 'Firstname Lastname' title case.

    Handles:
      'SILVERMAN, Eric'          →  'Eric Silverman'
      'Dave MURITU'              →  'Dave Muritu'
      'Jeff FOWLER (post-92)'    →  'Jeff Fowler'
      'Jelena Timotijevic-AR'    →  'Jelena Timotijevic'
      '[declared elected] Name'  →  'Name'
    """
    if not name or not name.strip():
        return name

    s = name.strip()

    # 1. Strip [bracket] annotations
    s = _BRACKET_ANNOT.sub("", s).strip()

    # 2. Strip known parenthetical qualifiers (post-92, AR, pronouns, etc.)
    s = _PAREN_QUALIFIERS.sub("", s).strip()

    # 3. Strip fused qualifiers e.g. -post-92, -AR
    s = _FUSED_SUFFIXES.sub("", s).strip()

    # 4. Strip remaining parentheticals (institutions, other qualifiers)
    s = re.sub(r"\([^)]*\)", "", s).strip()

    # 5. Strip leading honorifics (Dr, Mr, Ms, Prof, etc.)
    s = _HONORIFICS.sub("", s).strip()

    # 6. Normalise whitespace
    s = " ".join(s.split())

    if not s:
        return name.strip()

    # 7. Detect LASTNAME, Firstname  (all-caps OR title-case single-word surname before comma)
    if "," in s:
        comma_idx = s.index(",")
        before = s[:comma_idx].strip()
        after  = s[comma_idx + 1:].strip()
        before_alpha = re.sub(r"[^A-Za-z]", "", before)
        # Trigger if before-comma is all-caps (standard count-sheet format)
        # OR is a single title-cased word that looks like a surname (e.g. "Blake, Vicky")
        _is_allcaps  = before_alpha and before_alpha.isupper()
        _is_title_surname = (
            after
            and " " not in before.strip()          # single token before comma
            and before_alpha                        # non-empty alpha
            and before_alpha[0].isupper()           # starts uppercase
            and before_alpha[1:].islower()          # rest lowercase (title case)
            and before_alpha[0].isalpha()
            and after.strip()[0].isupper()          # firstname also starts upper
        )
        if (_is_allcaps or _is_title_surname) and after:
            after = _HONORIFICS.sub("", after).strip()
            lastname  = " ".join(_cap_word(w) for w in before.split())
            firstname = " ".join(_cap_word(w) for w in after.split())
            return f"{firstname} {lastname}"

    # 8. Per-token: title-case all-caps surname tokens (Firstname LASTNAME)
    tokens = s.split()
    result = [_cap_word(t) if _is_allcaps_token(t) else t for t in tokens]
    s = " ".join(result)

    # 9. If wholly lowercase (HTML-scraped plain names), apply title case
    if s == s.lower():
        s = " ".join(_cap_word(w) for w in s.split())

    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def year_from_dir(dir_name: str) -> str:
    """Extract the raw year portion of a directory name (strip _suffix)."""
    return re.split(r"_", dir_name, maxsplit=1)[0]


def _display_year(raw: str) -> str:
    """Canonical year label: '2019-20' → '2020', single years unchanged."""
    if len(raw) > 4 and ("-" in raw[4:] or "/" in raw[4:]):
        return raw[:2] + raw[5:]
    return raw


def canonical_year(dir_name: str) -> str:
    """Canonical display year for a raw directory name."""
    return _display_year(year_from_dir(dir_name))


def election_id_for(year: str, election_type: str, contest_name: str = "") -> str:
    """Compute election_id from canonical year, type, and contest name.

    Regular elections:    '2020'
    Casual vacancies:     '2020/cv'
    Standalone GS:        '2019/gs'
    Concurrent GS stays the same as the national election_id.
    """
    if election_type == "casual vacancy":
        return f"{year}/cv"
    if election_type == "general secretary":
        return f"{year}/gs"
    # CV contest embedded in a UK national election (contest name contains 'casual vacancy')
    if re.search(r"casual.vacanc", contest_name or "", re.IGNORECASE):
        return f"{year}/cv"
    return year


def election_type_from_dir(dir_name: str) -> str:
    suffix_map = {
        "gs": "general secretary",
        "scotland": "Scotland",
        "cv": "casual vacancy",
    }
    parts = dir_name.split("_", 1)
    if len(parts) == 2:
        return suffix_map.get(parts[1], "UK national")
    return "UK national"


def load_position_map() -> dict[str, str]:
    """Return {position_raw_lower: canonical_name} from position_map.csv if it exists."""
    if not POSITION_MAP_PATH.exists():
        return {}
    with POSITION_MAP_PATH.open() as f:
        return {
            row["position_raw"].strip().lower(): row["canonical"].strip()
            for row in csv.DictReader(f)
            if row.get("canonical")
        }


def canonical_position(raw: str, pos_map: dict) -> str:
    return pos_map.get(raw.strip().lower(), raw.strip())


# ---------------------------------------------------------------------------
# PDF records → rows
# ---------------------------------------------------------------------------

def process_pdf_records(
    dir_name: str,
    records: list[dict],
    pos_map: dict,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Convert a list of pdf_records contest dicts into three flat row lists:
    (contest_rows, candidate_rows, round_rows).
    """
    year = canonical_year(dir_name)
    election_type = election_type_from_dir(dir_name)

    contest_rows: list[dict] = []
    candidate_rows: list[dict] = []
    round_rows: list[dict] = []

    # Pre-scan: find contest names that appear with multiple distinct seat counts.
    # These are genuinely different contests (e.g. "UK Elected Members" in FE vs HE
    # PDFs) and need disambiguating suffixes in their contest_id.
    _name_seat_sets: dict[str, set] = {}
    for _c in records:
        _cn = " ".join(_c["contest_name"].split())
        _name_seat_sets.setdefault(_cn, set()).add(_c.get("seats"))
    _ambiguous_names: set[str] = {
        n for n, ss in _name_seat_sets.items()
        if len({s for s in ss if s is not None}) > 1
    }

    for contest in records:
        contest_name_raw = contest["contest_name"]
        # Normalise whitespace in contest name (multi-line names from PDFs)
        contest_name_clean = " ".join(contest_name_raw.split())
        position = canonical_position(contest_name_clean, pos_map)

        # When the same contest name is used for contests with different seat counts
        # (e.g. FE vs HE "UK Elected Members"), disambiguate by appending seat count.
        seats_raw = contest.get("seats")
        if contest_name_clean in _ambiguous_names and seats_raw is not None:
            contest_name_clean = f"{contest_name_clean} ({seats_raw} seats)"
            position = canonical_position(contest_name_clean, pos_map)

        eid        = election_id_for(year, election_type, contest_name_clean)
        contest_id = f"{eid}|{election_type}|{contest_name_clean}"

        # Determine if we have actual STV rounds
        has_rounds = any(bool(c["rounds"]) for c in contest.get("candidates", []))

        contest_rows.append({
            "contest_id": contest_id,
            "year": year,
            "election_id": eid,
            "election_type": election_type,
            "contest_name_raw": contest_name_raw,
            "contest_name": contest_name_clean,
            "position": position,
            "date": contest.get("date", ""),
            "seats": contest.get("seats", ""),
            "valid_votes": contest.get("valid_votes", ""),
            "invalid_votes": contest.get("invalid_votes", ""),
            "quota": contest.get("quota", ""),
            "election_rules": contest.get("election_rules", ""),
            "has_stv_rounds": has_rounds,
            "source": "pdf",
            "source_pdf": contest.get("source_pdf", ""),
        })

        source_pdf = contest.get("source_pdf", "")
        for cand in contest.get("candidates", []):
            name = cand.get("name") or cand.get("name_raw", "")
            flags = cand.get("demographic_flags", [])

            candidate_rows.append({
                "contest_id": contest_id,
                "year": year,
                "election_id": eid,
                "election_type": election_type,
                "contest_name": contest_name_clean,
                "position": position,
                "name": name,
                "name_raw": cand.get("name_raw", name),
                "demographic_flags": "|".join(flags) if flags else "",
                "is_woman": "woman" in flags,
                "is_post92": "post-92" in flags,
                "is_academic_related": "academic related" in flags,
                "outcome": cand.get("outcome", ""),
                "first_preferences": _first_pref(cand.get("rounds", {})),
                "source": "pdf",
                "_source_pdf": source_pdf,  # used for dedup, stripped before writing
            })

            for round_str, rdata in cand.get("rounds", {}).items():
                round_rows.append({
                    "contest_id": contest_id,
                    "year": year,
                    "name": name,
                    "round": int(round_str),
                    "votes": rdata.get("votes"),
                    "transfer": rdata.get("transfer"),
                    "eliminated": rdata.get("eliminated", False),
                })

    return contest_rows, candidate_rows, round_rows


def _first_pref(rounds: dict) -> float | None:
    if not rounds:
        return None
    # Rounds keys are strings; "1" is first preferences
    r1 = rounds.get("1")
    if r1:
        return r1.get("votes")
    return None


# ---------------------------------------------------------------------------
# HTML records → rows
# ---------------------------------------------------------------------------

def process_html_records(
    html_records: list[dict],
    existing_contest_ids: set[str],
    pos_map: dict,
    dir_name: str = "",
) -> tuple[list[dict], list[dict]]:
    """
    Convert html_records (uncontested / no-nomination) to contest + candidate rows.
    Skip any contest_id already covered by PDF records.
    """
    contest_rows: list[dict] = []
    candidate_rows: list[dict] = []

    # Group by (year, position_raw) to avoid duplicate contest rows
    seen_contests: set[str] = set()

    for rec in html_records:
        year = _display_year(rec["year"])   # canonicalize "2019-20" → "2020"
        position_raw = rec["position_raw"]
        # Strip seats count from position heading, e.g. "Midlands HE (3 seats)"
        position_clean = re.sub(r"\s*\(\d+\s+seat[s]?\)\s*", "", position_raw).strip()
        position = canonical_position(position_clean, pos_map)
        election_type = election_type_from_dir(dir_name) if dir_name else "UK national"

        eid        = election_id_for(year, election_type, position_clean)
        contest_id = f"{eid}|{election_type}|{position_clean}"

        # Don't duplicate contests already extracted from PDFs
        if contest_id in existing_contest_ids:
            continue

        if contest_id not in seen_contests:
            seen_contests.add(contest_id)
            # Extract seats from heading if present
            seats_m = re.search(r"\((\d+)\s+seat[s]?\)", position_raw)
            contest_rows.append({
                "contest_id": contest_id,
                "year": year,
                "election_id": eid,
                "election_type": election_type,
                "contest_name_raw": position_raw,
                "contest_name": position_clean,
                "position": position,
                "date": "",
                "seats": seats_m.group(1) if seats_m else "",
                "valid_votes": "",
                "invalid_votes": "",
                "quota": "",
                "election_rules": "",
                "has_stv_rounds": False,
                "source": "html",
                "source_pdf": "",
            })

        outcome = rec["outcome"]
        name = rec.get("candidate_name") or ""

        candidate_rows.append({
            "contest_id": contest_id,
            "year": year,
            "election_id": eid,
            "election_type": election_type,
            "contest_name": position_clean,
            "position": position,
            "name": name,
            "name_raw": name,
            "demographic_flags": "",
            "is_woman": False,
            "is_post92": False,
            "is_academic_related": False,
            "outcome": outcome,
            "first_preferences": 0 if outcome == "Uncontested" else None,
            "source": "html",
            "_source_pdf": "",
        })

    return contest_rows, candidate_rows


# ---------------------------------------------------------------------------
# Deduplication: prefer count-sheet records over ROV records
# ---------------------------------------------------------------------------

def deduplicate_contests(
    contest_rows: list[dict],
    candidate_rows: list[dict],
    round_rows: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    When the same contest appears in both a ROV summary PDF (no STV rounds)
    and an individual count-sheet PDF (with STV rounds), keep only the
    count-sheet version.

    Matching heuristic: same year + election_type + normalised contest name.
    """
    # Find contest_ids that have STV rounds
    has_rounds_ids: set[str] = {r["contest_id"] for r in round_rows}

    # For each (year, election_type, normalised_name) group, prefer the
    # entry with STV rounds when there's a conflict.
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in contest_rows:
        key = (c["year"], c["election_type"], _norm(c["contest_name"]))
        groups[key].append(c)

    # Map contest_id -> winning source_pdf (so candidates can be filtered)
    winner_pdf: dict[str, str] = {}
    kept_ids: set[str] = set()
    deduped_contests: list[dict] = []
    for key, group in groups.items():
        if len(group) == 1:
            chosen = group[0]
        else:
            # Prefer the one with STV rounds
            with_rounds = [c for c in group if c["contest_id"] in has_rounds_ids]
            chosen = with_rounds[0] if with_rounds else group[0]
        kept_ids.add(chosen["contest_id"])
        winner_pdf[chosen["contest_id"]] = chosen.get("source_pdf", "")
        deduped_contests.append(chosen)

    # Keep only candidates from the winning PDF (or html/non-pdf sources)
    deduped_candidates = []
    for c in candidate_rows:
        cid = c["contest_id"]
        if cid not in kept_ids:
            continue
        src_pdf = c.get("_source_pdf", "")
        win_pdf = winner_pdf.get(cid, "")
        # If this candidate came from a PDF, it must match the winner's PDF
        if c.get("source") == "pdf" and src_pdf and win_pdf and src_pdf != win_pdf:
            continue
        deduped_candidates.append(c)
    deduped_rounds = [r for r in round_rows if r["contest_id"] in kept_ids]

    # Secondary pass: ROV-only contests whose valid_votes match a with-rounds contest
    # in the same year+election_type are duplicates with different name strings.
    with_rounds_vv: set[tuple] = set()
    for c in deduped_contests:
        if c["contest_id"] not in has_rounds_ids:
            continue
        vv = c.get("valid_votes")
        if vv is None or vv == "":
            continue
        try:
            with_rounds_vv.add((c["year"], c["election_type"], int(float(str(vv)))))
        except (ValueError, TypeError):
            pass

    rov_drop: set[str] = set()
    for c in deduped_contests:
        if c["contest_id"] in has_rounds_ids:
            continue
        vv = c.get("valid_votes")
        if vv is None or vv == "":
            continue
        try:
            key = (c["year"], c["election_type"], int(float(str(vv))))
        except (ValueError, TypeError):
            continue
        if key in with_rounds_vv:
            rov_drop.add(c["contest_id"])

    if rov_drop:
        print(f"Deduplication (secondary): dropped {len(rov_drop)} ROV-only contest(s) matched by valid_votes to count sheets")
        deduped_contests   = [c for c in deduped_contests   if c["contest_id"] not in rov_drop]
        deduped_candidates = [c for c in deduped_candidates if c["contest_id"] not in rov_drop]
        deduped_rounds     = [r for r in deduped_rounds     if r["contest_id"] not in rov_drop]

    return deduped_contests, deduped_candidates, deduped_rounds


def _norm(name: str) -> str:
    """Normalise contest name for dedup matching."""
    return re.sub(r"\W+", " ", name.lower()).strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CONTEST_FIELDS = [
    "contest_id", "year", "election_id", "election_type",
    "contest_name_raw", "contest_name",
    "position", "date", "seats", "valid_votes", "invalid_votes", "quota",
    "election_rules", "has_stv_rounds", "source", "source_pdf",
]

CANDIDATE_FIELDS = [
    "contest_id", "year", "election_id", "election_type", "contest_name", "position",
    "name", "name_raw", "name_canonical", "demographic_flags",
    "is_woman", "is_post92", "is_academic_related",
    "outcome", "first_preferences", "source",
]

ROUND_FIELDS = [
    "contest_id", "year", "name", "round", "votes", "transfer", "eliminated",
]

BALLOT_FIELDS = [
    "year", "election_id", "election_type", "ballot_type",
    "eligible_voters", "votes_cast", "turnout_pct",
    "suspect", "suspect_reason", "source_pdf",
]

# Thresholds below which HE/FE rows are considered partial (regional) rather than
# full-sector ballots, based on known data structure (see DATA_ISSUES.md)
_HE_MIN_ELIGIBLE = 5_000
_FE_MIN_ELIGIBLE = 3_000

# (election_id, ballot_type) pairs known to be mislabelled or from non-annual ballots
_KNOWN_SUSPECT: dict[tuple, str] = {
    ("2011", "HE"): "report covers national contests (VP/Treasurer), not HE-only",
    ("2021/cv", "FE"): "casual vacancy ballot (2021_cv), not annual FE election",
}


def flag_suspect(row: dict) -> dict:
    """Add suspect + suspect_reason fields to a ballot row."""
    reason = ""
    if row.get("election_type") != "UK national":
        reason = f"election_type is '{row['election_type']}', not a main annual ballot"
    elif (row.get("election_id", row["year"]), row["ballot_type"]) in _KNOWN_SUSPECT:
        reason = _KNOWN_SUSPECT[(row.get("election_id", row["year"]), row["ballot_type"])]
    elif row["ballot_type"] == "HE":
        e = row.get("eligible_voters") or 0
        if e < _HE_MIN_ELIGIBLE:
            reason = f"eligible_voters={e} too small for full HE ballot (regional count sheet?)"
    elif row["ballot_type"] == "FE":
        e = row.get("eligible_voters") or 0
        if e < _FE_MIN_ELIGIBLE:
            reason = f"eligible_voters={e} too small for full FE ballot (regional count sheet?)"
    return {**row, "suspect": bool(reason), "suspect_reason": reason}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    pos_map = load_position_map()
    if pos_map:
        print(f"Loaded {len(pos_map)} position mappings from position_map.csv")

    all_contests: list[dict] = []
    all_candidates: list[dict] = []
    all_rounds: list[dict] = []
    all_ballots: list[dict] = []

    dirs = sorted(RAW_DIR.iterdir())
    for d in dirs:
        pdf_path = d / "pdf_records.json"
        html_path = d / "html_records.json"
        stats_path = d / "ballot_stats.json"

        if not pdf_path.exists() and not html_path.exists():
            continue

        pdf_records = json.loads(pdf_path.read_text()) if pdf_path.exists() else []
        html_records = json.loads(html_path.read_text()) if html_path.exists() else []

        # Ballot stats (extracted from PDFs)
        if stats_path.exists():
            year  = canonical_year(d.name)
            etype = election_type_from_dir(d.name)
            eid   = election_id_for(year, etype)
            for stat in json.loads(stats_path.read_text()):
                all_ballots.append({
                    "year": year,
                    "election_id": eid,
                    "election_type": etype,
                    **stat,
                })

        c_rows, ca_rows, r_rows = process_pdf_records(d.name, pdf_records, pos_map)

        if args.verbose and c_rows:
            n_rounds = sum(1 for c in c_rows if c["has_stv_rounds"])
            print(f"  {d.name}: {len(c_rows)} contests ({n_rounds} with STV rounds), "
                  f"{len(ca_rows)} candidates, {len(r_rows)} round-rows")

        # HTML records: don't add contests already in PDF records
        existing_ids = {c["contest_id"] for c in c_rows}
        hc_rows, hca_rows = process_html_records(html_records, existing_ids, pos_map, d.name)

        all_contests.extend(c_rows + hc_rows)
        all_candidates.extend(ca_rows + hca_rows)
        all_rounds.extend(r_rows)

    # Manual ballot stats (hand-entered for image PDFs / missing years)
    if MANUAL_BALLOTS_PATH.exists():
        with MANUAL_BALLOTS_PATH.open() as f:
            for row in csv.DictReader(f):
                yr    = _display_year(row["year"])   # canonicalize "2021-22" → "2022"
                etype = row["election_type"]
                all_ballots.append({
                    "year":             yr,
                    "election_id":      election_id_for(yr, etype),
                    "election_type":    etype,
                    "ballot_type":      row["ballot_type"],
                    "eligible_voters":  int(row["eligible_voters"]),
                    "votes_cast":       int(row["votes_cast"]),
                    "turnout_pct":      float(row["turnout_pct"]),
                    "source_pdf":       row["source_note"],
                })
        print(f"Loaded {sum(1 for _ in csv.DictReader(MANUAL_BALLOTS_PATH.open()))} manual ballot rows")

    # Deduplicate ROV vs count-sheet overlaps
    before = len(all_contests)
    all_contests, all_candidates, all_rounds = deduplicate_contests(
        all_contests, all_candidates, all_rounds
    )
    dropped = before - len(all_contests)
    if dropped:
        print(f"Deduplication: dropped {dropped} ROV-only contest(s) superseded by count sheets")

    # Infer missing seat counts from elected candidate counts.
    # ROV-format records often omit explicit seat numbers; the number of elected
    # candidates is a reliable lower bound (may undercount if seats went unfilled).
    elected_counts: dict[str, int] = {}
    for ca in all_candidates:
        if ca.get("outcome") in ("Elected", "Uncontested"):
            elected_counts[ca["contest_id"]] = elected_counts.get(ca["contest_id"], 0) + 1
    inferred = 0
    for c in all_contests:
        if c.get("seats") in (None, "", "nan"):
            n_elected = elected_counts.get(c["contest_id"], 0)
            if n_elected > 0:
                c["seats"] = n_elected
                inferred += 1
    if inferred:
        print(f"Inferred seats for {inferred} contest(s) from elected count")

    # Add name_canonical column
    for ca in all_candidates:
        ca["name_canonical"] = normalise_name(ca.get("name") or "")

    # Within-contest dedup: same (contest_id, name_canonical) → keep the row
    # with actual vote data; without it, prefer Elected/Uncontested over others.
    from collections import defaultdict
    _cand_groups: dict[tuple, list] = defaultdict(list)
    for ca in all_candidates:
        key = (ca["contest_id"], ca["name_canonical"].strip().lower())
        _cand_groups[key].append(ca)

    deduped_within: list[dict] = []
    within_dropped = 0
    for ca in all_candidates:
        key = (ca["contest_id"], ca["name_canonical"].strip().lower())
        group = _cand_groups[key]
        if len(group) == 1:
            deduped_within.append(ca)
            continue
        # Only process each group once
        if ca is not group[0]:
            continue
        within_dropped += len(group) - 1
        with_votes = [r for r in group if r.get("first_preferences") not in (None, "", "nan")]
        chosen = with_votes[0] if with_votes else group[0]
        # When STV rounds are split across two entries (different outcome per entry),
        # the final outcome is what matters: prefer Elected > Uncontested > others.
        OUTCOME_PRIORITY = {"Elected": 0, "Uncontested": 1}
        best_outcome = min(
            (r["outcome"] for r in group if r.get("outcome")),
            key=lambda o: OUTCOME_PRIORITY.get(o, 99),
            default=chosen.get("outcome"),
        )
        if best_outcome != chosen.get("outcome"):
            chosen = dict(chosen)   # don't mutate the original
            chosen["outcome"] = best_outcome
        deduped_within.append(chosen)
    all_candidates = deduped_within
    if within_dropped:
        print(f"Within-contest dedup: dropped {within_dropped} duplicate candidate row(s)")

    distinct_before = len({(ca.get("name") or "").strip().lower() for ca in all_candidates if ca.get("name")})
    distinct_after  = len({ca["name_canonical"].strip().lower() for ca in all_candidates if ca.get("name_canonical")})
    print(f"Name normalisation: {distinct_before} raw distinct → {distinct_after} canonical distinct")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    # Deduplicate ballots: same election_id+ballot_type, keep highest eligible_voters
    ballot_key: dict[tuple, dict] = {}
    for b in all_ballots:
        key = (b["election_id"], b["ballot_type"])
        existing = ballot_key.get(key)
        if existing is None or (b.get("eligible_voters") or 0) > (existing.get("eligible_voters") or 0):
            ballot_key[key] = b
    deduped_ballots = sorted(
        [flag_suspect(b) for b in ballot_key.values()],
        key=lambda r: (r["year"], r["ballot_type"]),
    )

    write_csv(OUT_DIR / "contests.csv", all_contests, CONTEST_FIELDS)
    write_csv(OUT_DIR / "candidates.csv", all_candidates, CANDIDATE_FIELDS)
    write_csv(OUT_DIR / "stv_rounds.csv", all_rounds, ROUND_FIELDS)
    write_csv(OUT_DIR / "ballots.csv", deduped_ballots, BALLOT_FIELDS)

    print(f"\nWrote to {OUT_DIR}/")
    print(f"  contests.csv:   {len(all_contests)} rows")
    print(f"  candidates.csv: {len(all_candidates)} rows")
    print(f"  stv_rounds.csv: {len(all_rounds)} rows")
    print(f"  ballots.csv:    {len(deduped_ballots)} rows")

    # Summary stats
    with_rounds = sum(1 for c in all_contests if c["has_stv_rounds"])
    print(f"\n  {with_rounds}/{len(all_contests)} contests have STV round data")
    years = sorted({c["year"] for c in all_contests})
    print(f"  Years covered: {years[0]} – {years[-1]} ({len(years)} distinct years)")


if __name__ == "__main__":
    main()
