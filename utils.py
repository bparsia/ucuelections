"""Shared data loading and helpers for UCU Elections Streamlit pages."""

from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR    = Path(__file__).parent / "data" / "processed"
SOURCES_DIR = Path(__file__).parent / "sources"

GS_CONCURRENT = {"2012", "2017", "2023-24"}
GS_STANDALONE  = {"2019"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _csv_mtime() -> float:
    return max(p.stat().st_mtime for p in DATA_DIR.glob("*.csv"))


@st.cache_data
def load_data(mtime: float):  # mtime forces cache-bust when CSVs change
    contests   = pd.read_csv(DATA_DIR / "contests.csv")
    candidates = pd.read_csv(DATA_DIR / "candidates.csv")
    ballots    = pd.read_csv(DATA_DIR / "ballots.csv")
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
    """Sort '2019-20' after '2019'; synthetic '_gs' suffix sorts just after base year."""
    if y.endswith("_gs"):
        return year_sort_key(y[:-3]) + 0.25
    digits = y[:4]
    try:
        base = float(digits)
    except ValueError:
        return 9999.0
    return base + 0.5 if "-" in y or "/" in y else base


def display_year(y: str) -> str:
    """'2019-20' → '2020', '2019_gs' → '2019-GS'; single years unchanged."""
    if y.endswith("_gs"):
        return display_year(y[:-3]) + "-GS"
    if len(y) > 4 and ("-" in y[4:] or "/" in y[4:]):
        return y[:2] + y[5:]
    return y


# ---------------------------------------------------------------------------
# URL lookups
# ---------------------------------------------------------------------------

def _build_year_urls() -> dict[str, str]:
    pages    = pd.read_csv(SOURCES_DIR / "election_pages.csv")
    uk       = pages[(pages["election_type"] == "UK national") & (pages["include"] == "yes")]
    urls     = dict(zip(uk["year"].astype(str), uk["url"]))
    gs_pages = pages[(pages["election_type"] == "general secretary") & (pages["include"] == "yes")]
    for _, row in gs_pages.iterrows():
        urls[str(row["year"]) + "_gs"] = row["url"]
    return urls


YEAR_URLS: dict[str, str] = _build_year_urls()
