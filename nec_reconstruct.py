"""Reconstruct NEC/FEC/HEC membership year-by-year from election results."""

import csv
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VP_START_POSITIONS = {
    "Vice-President, FE":                  ("FE", 0),
    "Vice-President, HE":                  ("HE", 0),
    "Vice-President HE (Casual Vacancy)":  ("HE", 0),
    "President-elect, FE":                 ("FE", 1),   # 2007 founding election only
    "President-elect, HE":                 ("HE", 1),   # 2007 founding election only
}

CHAIN_ROLES = [
    "Vice-President",
    "President-elect",
    "President",
    "Immediate Past President",
]

NEC_REGULAR_POSITIONS = {
    "General Secretary", "Honorary Treasurer",
    "UK NEC Members, FE", "UK NEC Members, HE",
    "NEC Members, London and the East, FE", "NEC Members, London and the East, HE",
    "NEC Members, Midlands, FE", "NEC Members, Midlands, HE",
    "NEC Members, North East, FE", "NEC Members, North East, HE",
    "NEC Members, North West, FE", "NEC Members, North West, HE",
    "NEC Members, Northern Ireland, FE", "NEC Members, Northern Ireland, HE",
    "NEC Members, South, FE", "NEC Members, South, HE",
    "NEC Members, Wales, FE", "NEC Members, Wales, HE",
    "UCU Scotland President", "UCU Scotland Honorary Secretary",
    "UCU Scotland NEC Members, HE",
    "Vice-President, UCU Wales",
    "Representatives of Women Members, FE", "Representatives of Women Members, HE",
    "Representatives of Black Members",
    "Representatives of Migrant Members",
    "Representatives of Disabled Members, FE", "Representatives of Disabled Members, HE",
    "Representatives of LGBT+ Members",
    "Representatives of LGBT+ Members, FE", "Representatives of LGBT+ Members, HE",
    "Representatives of Casually Employed Members, FE", "Representatives of Casually Employed Members, HE",
    "Representatives of Members in Land-Based Education",
    "Trustees",
}

# ---------------------------------------------------------------------------
# Sector and role-type assignment
# ---------------------------------------------------------------------------

_SCOTLAND_POSITIONS = {
    "UCU Scotland President",
    "UCU Scotland Honorary Secretary",
    "UCU Scotland NEC Members, HE",
}


def _sector(position: str) -> str:
    """Return 'FE', 'HE', or 'national' for a position string."""
    if position.endswith(", FE"):
        return "FE"
    if position == "Vice-President, UCU Wales":
        return "FE"
    if position == "Representatives of Members in Land-Based Education":
        return "FE"
    if position.endswith(", HE"):
        return "HE"
    if position in _SCOTLAND_POSITIONS:
        return "HE"
    # national
    return "national"


def _role_type(position: str) -> str:
    """Return a role-type label for a regular NEC position."""
    if position in ("General Secretary", "Honorary Treasurer"):
        return "officer"
    if position in ("UK NEC Members, FE", "UK NEC Members, HE"):
        return "uk_nec"
    if position.startswith("NEC Members,"):
        return "regional"
    if position in _SCOTLAND_POSITIONS or position == "Vice-President, UCU Wales":
        return "regional"
    if position.startswith("Representatives of Women Members"):
        return "women"
    if position.startswith("Representatives of"):
        return "equality"
    if position == "Trustees":
        return "trustee"
    return "other"


# ---------------------------------------------------------------------------
# VP corrections loader
# ---------------------------------------------------------------------------

CORRECTIONS_PATH = Path(__file__).parent / "review" / "vp_chain_corrections.csv"


def load_vp_corrections() -> dict:
    """
    Load VP chain corrections from review/vp_chain_corrections.csv if it exists.

    Returns dict keyed by (year_str, name_canonical) → correction row dict.
    Columns expected: year, name_canonical, skip, role, note
    """
    corrections: dict[tuple, dict] = {}
    if not CORRECTIONS_PATH.exists():
        return corrections
    with CORRECTIONS_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            year = row.get("year", "").strip()
            name = row.get("name_canonical", "").strip()
            if year and name:
                corrections[(year, name)] = row
    return corrections


# ---------------------------------------------------------------------------
# VP chain builder
# ---------------------------------------------------------------------------

def build_vp_chain(elected_rows: list[dict], corrections: dict) -> list[dict]:
    """
    Project VP chain membership for each elected VP / President-elect.

    For each row where the position is in VP_START_POSITIONS, project
    CHAIN_ROLES forward from the start_step (0 for VP, 1 for PE).

    Returns a list of membership dicts with:
        year, name_canonical, position, sector, role_type, elected_year
    """
    results: list[dict] = []
    for row in elected_rows:
        pos = row.get("position", "")
        if pos not in VP_START_POSITIONS:
            continue
        sector, start_step = VP_START_POSITIONS[pos]
        election_year = row["year"]
        name = row["name_canonical"]

        for step in range(start_step, len(CHAIN_ROLES)):
            # The chain year is election_year + (step - start_step)
            chain_year = str(int(election_year) + (step - start_step))
            role = CHAIN_ROLES[step]

            # Check for a correction
            corr = corrections.get((chain_year, name))
            if corr:
                if corr.get("skip", "").strip().lower() in ("1", "true", "yes"):
                    continue  # skip this step
                if corr.get("role", "").strip():
                    role = corr["role"].strip()

            results.append({
                "year":           chain_year,
                "name_canonical": name,
                "position":       role,
                "sector":         sector,
                "role_type":      "vp_chain",
                "elected_year":   election_year,
            })

    return results


# ---------------------------------------------------------------------------
# Main reconstruction
# ---------------------------------------------------------------------------

def _load_individual_sectors() -> dict:
    """
    Load individual-level sector for Black/Migrant member candidates from
    sector_research.csv. Returns {(year_str, name_canonical_lower): sector}.
    """
    path = Path(__file__).parent / "review" / "sector_research.csv"
    lookup: dict[tuple, str] = {}
    if not path.exists():
        return lookup
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            year = row.get("year", "").strip()
            name = row.get("name_canonical", "").strip().lower()
            sector = row.get("sector", "").strip()
            if year and name and sector in ("FE", "HE"):
                lookup[(year, name)] = sector
    return lookup


def reconstruct_nec(candidates_path: Path) -> tuple[list[dict], list[dict]]:
    """
    Reconstruct NEC membership year-by-year from candidates CSV.

    Returns (membership_rows, stability_rows).
    """
    # --- Load candidates ---
    with candidates_path.open(newline="", encoding="utf-8") as f:
        all_candidates = list(csv.DictReader(f))

    individual_sectors = _load_individual_sectors()

    # Filter: outcome in {Elected, Uncontested}, election_type in {UK national, casual vacancy}
    elected = [
        r for r in all_candidates
        if r.get("outcome") in ("Elected", "Uncontested")
        and r.get("election_type") in ("UK national", "casual vacancy")
        and r.get("name_canonical", "").strip()
        and r.get("position", "").strip()
    ]

    # All years present in data (as ints for arithmetic, stored as str)
    all_years_int = sorted({int(r["year"]) for r in elected})
    if not all_years_int:
        return [], []
    max_year_int = max(all_years_int)

    # --- VP chain ---
    corrections = load_vp_corrections()
    vp_rows = build_vp_chain(elected, corrections)

    # Only keep VP chain rows up to max data year
    vp_rows = [r for r in vp_rows if int(r["year"]) <= max_year_int]

    # --- Regular positions ---
    # Group elected rows by (year, position, name_canonical) — deduplicate source
    # For regular positions: committee[Y] = elected[Y] ∪ elected[Y-1]
    regular_elected = [
        r for r in elected
        if r["position"] in NEC_REGULAR_POSITIONS
    ]

    # Build lookup: year_int → list of elected rows for regular positions
    by_year: dict[int, list[dict]] = {}
    for r in regular_elected:
        y = int(r["year"])
        by_year.setdefault(y, []).append(r)

    membership_rows: list[dict] = []

    # Add VP chain rows
    membership_rows.extend(vp_rows)

    # Build regular membership rows for each year in range
    for y_int in all_years_int:
        y_str = str(y_int)
        prev_y = y_int - 1

        # Rows from this year's election (term year 1 of 2)
        current_elected = by_year.get(y_int, [])
        # Rows from previous year's election (term year 2 of 2)
        prev_elected = by_year.get(prev_y, [])

        for r in current_elected + prev_elected:
            pos_sector = _sector(r["position"])
            # For national-sector positions (Black/Migrant members), look up
            # individual sector from sector_research using their election year
            if pos_sector == "national" and _role_type(r["position"]) == "equality":
                ind = individual_sectors.get((r["year"], r["name_canonical"].lower()))
                if ind:
                    pos_sector = ind
            membership_rows.append({
                "year":           y_str,
                "name_canonical": r["name_canonical"],
                "position":       r["position"],
                "sector":         pos_sector,
                "role_type":      _role_type(r["position"]),
                "elected_year":   r["year"],
            })

    # --- Deduplicate on (year, name_canonical, position) ---
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for row in membership_rows:
        key = (row["year"], row["name_canonical"], row["position"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)

    # VP chain takes precedence: if someone is in the VP chain for year Y,
    # suppress their regular NEC seat rows for that year (they vacated it).
    vp_chain_person_years: set[tuple] = {
        (r["year"], r["name_canonical"]) for r in deduped if r["role_type"] == "vp_chain"
    }
    deduped = [
        r for r in deduped
        if r["role_type"] == "vp_chain"
        or (r["year"], r["name_canonical"]) not in vp_chain_person_years
    ]

    # Sort for readability
    deduped.sort(key=lambda r: (r["year"], r["role_type"], r["position"], r["name_canonical"]))

    # --- Stability analysis ---
    # For each year: who is on the committee (by name_canonical)
    members_by_year: dict[str, set[str]] = {}
    for row in deduped:
        y = row["year"]
        members_by_year.setdefault(y, set()).add(row["name_canonical"])

    ever_seen: set[str] = set()
    stability_rows: list[dict] = []

    for y_int in all_years_int:
        y_str = str(y_int)
        current = members_by_year.get(y_str, set())
        prev_y_str = str(y_int - 1)
        prev = members_by_year.get(prev_y_str, set())

        new_ever   = current - ever_seen
        new_vs_prev = current - prev

        total = len(current)
        pct_new_ever    = round(100 * len(new_ever)    / total, 1) if total else 0.0
        pct_new_vs_prev = round(100 * len(new_vs_prev) / total, 1) if total else 0.0

        stability_rows.append({
            "year":           y_str,
            "total_members":  total,
            "new_ever":       len(new_ever),
            "new_vs_prev":    len(new_vs_prev),
            "pct_new_ever":   pct_new_ever,
            "pct_new_vs_prev": pct_new_vs_prev,
        })

        ever_seen |= current

    return deduped, stability_rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

CANDIDATES_PATH = Path(__file__).parent / "data" / "processed" / "candidates.csv"
NEC_MEMBERSHIP_PATH = Path(__file__).parent / "data" / "processed" / "nec_membership.csv"
NEC_STABILITY_PATH  = Path(__file__).parent / "data" / "processed" / "nec_stability.csv"

MEMBERSHIP_FIELDS = ["year", "name_canonical", "position", "sector", "role_type", "elected_year"]
STABILITY_FIELDS  = ["year", "total_members", "new_ever", "new_vs_prev", "pct_new_ever", "pct_new_vs_prev"]


def main() -> None:
    membership_rows, stability_rows = reconstruct_nec(CANDIDATES_PATH)

    out_dir = NEC_MEMBERSHIP_PATH.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    _write(NEC_MEMBERSHIP_PATH, membership_rows, MEMBERSHIP_FIELDS)
    _write(NEC_STABILITY_PATH,  stability_rows,  STABILITY_FIELDS)

    print(f"  nec_membership.csv: {len(membership_rows)} rows")
    print(f"  nec_stability.csv:  {len(stability_rows)} rows")
    if stability_rows:
        print("\n  Stability sample (last 5 years):")
        for row in stability_rows[-5:]:
            print(f"    {row['year']}: {row['total_members']} members, "
                  f"{row['new_vs_prev']} new ({row['pct_new_vs_prev']}%)")


if __name__ == "__main__":
    main()
