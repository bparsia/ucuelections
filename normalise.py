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

def year_from_dir(dir_name: str) -> str:
    """Extract the year portion of a directory name (strip _suffix)."""
    return re.split(r"_", dir_name, maxsplit=1)[0]


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
    year = year_from_dir(dir_name)
    election_type = election_type_from_dir(dir_name)

    contest_rows: list[dict] = []
    candidate_rows: list[dict] = []
    round_rows: list[dict] = []

    for contest in records:
        contest_name_raw = contest["contest_name"]
        # Normalise whitespace in contest name (multi-line names from PDFs)
        contest_name_clean = " ".join(contest_name_raw.split())
        position = canonical_position(contest_name_clean, pos_map)

        contest_id = f"{year}|{election_type}|{contest_name_clean}"

        # Determine if we have actual STV rounds
        has_rounds = any(bool(c["rounds"]) for c in contest.get("candidates", []))

        contest_rows.append({
            "contest_id": contest_id,
            "year": year,
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
        year = rec["year"]
        position_raw = rec["position_raw"]
        # Strip seats count from position heading, e.g. "Midlands HE (3 seats)"
        position_clean = re.sub(r"\s*\(\d+\s+seat[s]?\)\s*", "", position_raw).strip()
        position = canonical_position(position_clean, pos_map)
        # Use "UK national" as default for HTML records (they come from UK national pages)
        election_type = "UK national"

        contest_id = f"{year}|{election_type}|{position_clean}"

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
    "contest_id", "year", "election_type", "contest_name_raw", "contest_name",
    "position", "date", "seats", "valid_votes", "invalid_votes", "quota",
    "election_rules", "has_stv_rounds", "source", "source_pdf",
]

CANDIDATE_FIELDS = [
    "contest_id", "year", "election_type", "contest_name", "position",
    "name", "name_raw", "demographic_flags",
    "is_woman", "is_post92", "is_academic_related",
    "outcome", "first_preferences", "source",
]

ROUND_FIELDS = [
    "contest_id", "year", "name", "round", "votes", "transfer", "eliminated",
]

BALLOT_FIELDS = [
    "year", "election_type", "ballot_type",
    "eligible_voters", "votes_cast", "turnout_pct",
    "suspect", "suspect_reason", "source_pdf",
]

# Thresholds below which HE/FE rows are considered partial (regional) rather than
# full-sector ballots, based on known data structure (see DATA_ISSUES.md)
_HE_MIN_ELIGIBLE = 5_000
_FE_MIN_ELIGIBLE = 3_000

# (year, ballot_type) pairs known to be mislabelled or from non-annual ballots
_KNOWN_SUSPECT: dict[tuple, str] = {
    ("2011", "HE"): "report covers national contests (VP/Treasurer), not HE-only",
    ("2021", "FE"): "casual vacancy ballot (2021_cv), not annual FE election",
}


def flag_suspect(row: dict) -> dict:
    """Add suspect + suspect_reason fields to a ballot row."""
    reason = ""
    if row.get("election_type") != "UK national":
        reason = f"election_type is '{row['election_type']}', not a main annual ballot"
    elif (row["year"], row["ballot_type"]) in _KNOWN_SUSPECT:
        reason = _KNOWN_SUSPECT[(row["year"], row["ballot_type"])]
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
            year = year_from_dir(d.name)
            etype = election_type_from_dir(d.name)
            for stat in json.loads(stats_path.read_text()):
                all_ballots.append({
                    "year": year,
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
        hc_rows, hca_rows = process_html_records(html_records, existing_ids, pos_map)

        all_contests.extend(c_rows + hc_rows)
        all_candidates.extend(ca_rows + hca_rows)
        all_rounds.extend(r_rows)

    # Manual ballot stats (hand-entered for image PDFs / missing years)
    if MANUAL_BALLOTS_PATH.exists():
        with MANUAL_BALLOTS_PATH.open() as f:
            for row in csv.DictReader(f):
                all_ballots.append({
                    "year":             row["year"],
                    "election_type":    row["election_type"],
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

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    # Deduplicate ballots: same year+election_type+ballot_type, keep highest eligible_voters
    # (avoids duplicates when multiple PDFs cover the same ballot)
    ballot_key: dict[tuple, dict] = {}
    for b in all_ballots:
        key = (b["year"], b["election_type"], b["ballot_type"])
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
