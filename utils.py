"""Shared data loading and helpers for UCU Elections Streamlit pages."""

from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR    = Path(__file__).parent / "data" / "processed"
SOURCES_DIR = Path(__file__).parent / "sources"

GS_CONCURRENT = {"2012", "2017", "2024"}   # canonical years (2023-24 → 2024)
GS_STANDALONE  = {"2019"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _csv_mtime() -> float:
    return max(p.stat().st_mtime for p in DATA_DIR.glob("*.csv"))


@st.cache_data
def load_data(mtime: float):  # mtime forces cache-bust when CSVs change
    contests   = pd.read_csv(DATA_DIR / "contests.csv",   dtype={"year": str, "election_id": str})
    candidates = pd.read_csv(DATA_DIR / "candidates.csv", dtype={"year": str, "election_id": str})
    ballots    = pd.read_csv(DATA_DIR / "ballots.csv",    dtype={"year": str, "election_id": str})
    contests["seats"]          = pd.to_numeric(contests["seats"],          errors="coerce")
    contests["valid_votes"]    = pd.to_numeric(contests["valid_votes"],    errors="coerce")
    ballots["eligible_voters"] = pd.to_numeric(ballots["eligible_voters"], errors="coerce")
    ballots["votes_cast"]      = pd.to_numeric(ballots["votes_cast"],      errors="coerce")
    ballots["turnout_pct"]     = pd.to_numeric(ballots["turnout_pct"],     errors="coerce")
    candidates["first_preferences"] = pd.to_numeric(
        candidates["first_preferences"], errors="coerce"
    )
    return contests, candidates, ballots


# ---------------------------------------------------------------------------
# Year helpers
# ---------------------------------------------------------------------------

def year_sort_key(y: str) -> float:
    """Sort key for canonical year or election_id strings.

    '2020'    → 2020.0
    '2019/gs' → 2019.25
    '2020/cv' → 2020.5
    '2020/cv1'→ 2020.5
    Legacy '_gs' suffix still handled for safety.
    """
    if y.endswith("_gs"):                       # legacy
        return year_sort_key(y[:-3]) + 0.25
    if "/" in y:
        base, suffix = y.split("/", 1)
        offsets = {"gs": 0.25, "cv": 0.5, "cv1": 0.5, "cv2": 0.6}
        return year_sort_key(base) + offsets.get(suffix, 0.1)
    try:
        return float(y[:4])
    except ValueError:
        return 9999.0


def display_year(y: str) -> str:
    """Human-readable label for a canonical year or election_id.

    '2020'    → '2020'
    '2019/gs' → '2019-GS'
    '2020/cv' → '2020-CV'
    Legacy academic-year formats still handled for safety.
    """
    if y.endswith("_gs"):                       # legacy
        return display_year(y[:-3]) + "-GS"
    if "/" in y:
        base, suffix = y.split("/", 1)
        label = {"gs": "GS", "cv": "CV", "cv1": "CV", "cv2": "CV"}.get(suffix, suffix.upper())
        return f"{base}-{label}"
    # Legacy academic-year format (should no longer appear in CSVs post-migration)
    if len(y) > 4 and ("-" in y[4:]):
        return y[:2] + y[5:]
    return y


# ---------------------------------------------------------------------------
# URL lookups
# ---------------------------------------------------------------------------

def _build_year_urls() -> dict[str, str]:
    """Build election_id → UCU page URL mapping with canonical year keys."""
    pages = pd.read_csv(SOURCES_DIR / "election_pages.csv")
    urls: dict[str, str] = {}
    uk = pages[(pages["election_type"] == "UK national") & (pages["include"] == "yes")]
    for _, row in uk.iterrows():
        urls[display_year(str(row["year"]))] = row["url"]   # "2019-20" → "2020"
    gs = pages[(pages["election_type"] == "general secretary") & (pages["include"] == "yes")]
    for _, row in gs.iterrows():
        canonical = display_year(str(row["year"]))
        urls[f"{canonical}/gs"] = row["url"]
    return urls


YEAR_URLS: dict[str, str] = _build_year_urls()
