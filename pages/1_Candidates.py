"""UCU Elections — Candidate analysis page."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st
from urllib.parse import quote

from utils import _csv_mtime, display_year, load_data, year_sort_key

contests, candidates, ballots = load_data(mtime=_csv_mtime())

st.title("Candidates")

uk = candidates[candidates["election_type"].isin({"UK national", "casual vacancy"})].copy()
name_col = "name_canonical" if "name_canonical" in uk.columns else "name"

# ---------------------------------------------------------------------------
# Top vote-getters and top losers
# ---------------------------------------------------------------------------

with_votes = uk[uk["first_preferences"].notna() & (uk["first_preferences"] > 0)].copy()
with_votes["Year"] = with_votes["year"].apply(display_year)

# Final votes from STV rounds (last round each candidate appears)
_rounds_path = Path(__file__).parent.parent / "data" / "processed" / "stv_rounds.csv"

@st.cache_data
def _load_final_votes(mtime: float) -> dict:
    rounds = pd.read_csv(_rounds_path, dtype={"year": str})
    rounds["round"] = rounds["round"].astype(int)
    idx = rounds.groupby(["contest_id", "name"])["round"].idxmax()
    return rounds.loc[idx].set_index(["contest_id", "name"])["votes"].to_dict()

_final_votes = _load_final_votes(mtime=_csv_mtime())

winners = with_votes[with_votes["outcome"].isin({"Elected", "Uncontested"})].copy()
winners["final_votes"] = winners.apply(
    lambda r: _final_votes.get((r["contest_id"], r["name"])), axis=1
)

def _fmt_winner_row(df: pd.DataFrame) -> pd.DataFrame:
    out = (
        df[[name_col, "Year", "contest_name", "first_preferences", "final_votes"]]
        .rename(columns={
            name_col:            "Candidate",
            "contest_name":      "Contest",
            "first_preferences": "1st prefs",
            "final_votes":       "Final votes",
        })
        .reset_index(drop=True)
    )
    out["Final votes"] = out.apply(
        lambda r: f"{r['Final votes']:,.1f}"
        if pd.notna(r["Final votes"]) and abs(r["Final votes"] - r["1st prefs"]) > 0.05
        else "—",
        axis=1,
    )
    out["1st prefs"] = out["1st prefs"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "—")
    return out

st.subheader("Top 20 vote-getters (winners, final votes)")
top = _fmt_winner_row(winners.nlargest(20, "final_votes"))
top.index += 1
st.dataframe(top, use_container_width=True)

st.subheader("Bottom 20 vote-getters (winners, final votes)")
st.caption("Elected candidates with the lowest final vote tally — excludes uncontested seats.")
contested_winners = winners[winners["outcome"] == "Elected"].dropna(subset=["final_votes"])
bot = _fmt_winner_row(contested_winners.nsmallest(20, "final_votes"))
bot.index += 1
st.dataframe(bot, use_container_width=True)

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
)
appearances["Candidate"] = appearances["Candidate"].apply(
    lambda n: f"[{n}](/Candidate?candidate={quote(n)})"
)
appearances = (appearances
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
