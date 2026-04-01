"""UCU Elections — Candidate analysis page."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from utils import _csv_mtime, display_year, load_data, year_sort_key

contests, candidates, ballots = load_data(mtime=_csv_mtime())

st.title("Candidates")

uk = candidates[candidates["election_type"] == "UK national"].copy()
name_col = "name_canonical" if "name_canonical" in uk.columns else "name"

# ---------------------------------------------------------------------------
# Top vote-getters and top losers
# ---------------------------------------------------------------------------

with_votes = uk[uk["first_preferences"].notna() & (uk["first_preferences"] > 0)].copy()
with_votes["Year"] = with_votes["year"].apply(display_year)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Top 20 vote-getters (first preferences)")
    top = (
        with_votes
        .nlargest(20, "first_preferences")
        [[name_col, "Year", "contest_name", "first_preferences", "outcome"]]
        .rename(columns={
            name_col:           "Candidate",
            "contest_name":     "Contest",
            "first_preferences": "1st prefs",
            "outcome":          "Outcome",
        })
        .reset_index(drop=True)
    )
    top.index += 1
    st.dataframe(top, use_container_width=True)

with col2:
    st.subheader("Top 20 losing vote-getters")
    losers = (
        with_votes[with_votes["outcome"] == "Not Elected"]
        .nlargest(20, "first_preferences")
        [[name_col, "Year", "contest_name", "first_preferences"]]
        .rename(columns={
            name_col:           "Candidate",
            "contest_name":     "Contest",
            "first_preferences": "1st prefs",
        })
        .reset_index(drop=True)
    )
    losers.index += 1
    st.dataframe(losers, use_container_width=True)

# ---------------------------------------------------------------------------
# Career appearances table
# ---------------------------------------------------------------------------

st.subheader("Most appearances in UK national elections")
st.caption("Counts distinct years in which each candidate appeared, with win rate.")

def _fmt_years_bold(group: pd.DataFrame) -> str:
    """Return elections string with winning elections in bold markdown."""
    eid_col = "election_id" if "election_id" in group.columns else "year"
    winning = set(group.loc[group["outcome"].isin({"Elected", "Uncontested"}), eid_col])
    parts = []
    for eid in sorted(group[eid_col].unique(), key=year_sort_key):
        dy = display_year(eid)
        parts.append(f"**{dy}**" if eid in winning else dy)
    return ", ".join(parts)

appearances = (
    uk.groupby(name_col)
    .apply(lambda g: pd.Series({
        "Elections": g["election_id"].nunique() if "election_id" in g.columns else g["year"].nunique(),
        "Wins":      g["outcome"].isin({"Elected", "Uncontested"}).sum(),
        "Years":     _fmt_years_bold(g),
    }), include_groups=False)
    .reset_index()
    .rename(columns={name_col: "Candidate"})
    .sort_values(["Elections", "Wins"], ascending=False)
    .head(40)
    .reset_index(drop=True)
)
appearances["Win rate"] = appearances.apply(
    lambda r: f"{int(r['Wins'] / r['Elections'] * 100)}%" if r["Elections"] else "—",
    axis=1,
)
appearances = appearances[["Candidate", "Elections", "Wins", "Win rate", "Years"]]

# Render as markdown table so bold formatting in Years column is visible
header = "| " + " | ".join(appearances.columns) + " |"
sep    = "| " + " | ".join("---" for _ in appearances.columns) + " |"
rows   = "\n".join(
    "| " + " | ".join(str(v) for v in row) + " |"
    for row in appearances.itertuples(index=False)
)
st.markdown(f"{header}\n{sep}\n{rows}")
