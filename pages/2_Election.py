"""UCU Elections — per-year election report page."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from utils import (
    GS_CONCURRENT, GS_STANDALONE, YEAR_URLS,
    _csv_mtime, display_year, load_data, year_sort_key,
)

st.set_page_config(
    page_title="UCU Elections — Election Report",
    page_icon="🗳️",
    layout="wide",
)

contests, candidates, ballots = load_data(mtime=_csv_mtime())

uk_years = sorted(
    contests[contests["election_type"] == "UK national"]["year"].unique(),
    key=year_sort_key,
    reverse=True,
)

# ---------------------------------------------------------------------------
# Year selection — synced with ?year= query param
# ---------------------------------------------------------------------------

qp_year = st.query_params.get("year", uk_years[0])
if qp_year not in uk_years:
    qp_year = uk_years[0]

selected_year = st.selectbox(
    "Election year",
    uk_years,
    index=uk_years.index(qp_year),
    format_func=display_year,
)
if selected_year != qp_year:
    st.query_params["year"] = selected_year
    st.rerun()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

gs_note = ""
if selected_year in GS_CONCURRENT:
    gs_note = " ★ (concurrent General Secretary election)"
elif selected_year in GS_STANDALONE:
    gs_note = " ★ (standalone GS election this year)"

st.title(f"UCU NEC Election {display_year(selected_year)}{gs_note}")

# ---------------------------------------------------------------------------
# Ballot summary metrics
# ---------------------------------------------------------------------------

year_ballots = ballots[
    (ballots["year"] == selected_year)
    & (ballots["election_type"] == "UK national")
    & (~ballots["suspect"].astype(bool))
].sort_values("ballot_type")

if not year_ballots.empty:
    cols = st.columns(len(year_ballots))
    for col, (_, b) in zip(cols, year_ballots.iterrows()):
        elig = f"{int(b['eligible_voters']):,}" if pd.notna(b["eligible_voters"]) else "—"
        cast = f"{int(b['votes_cast']):,}"      if pd.notna(b["votes_cast"])      else "—"
        tpct = f"{b['turnout_pct']:.1f}%"       if pd.notna(b["turnout_pct"])     else "—"
        col.metric(
            label=f"{b['ballot_type']} ballot — turnout",
            value=tpct,
            help=f"Eligible: {elig} | Votes cast: {cast}",
        )
else:
    st.info("No ballot statistics available for this year.")

# ---------------------------------------------------------------------------
# Contests
# ---------------------------------------------------------------------------

year_contests = (
    contests[
        (contests["year"] == selected_year)
        & (contests["election_type"] == "UK national")
    ]
    .sort_values("contest_name")
)
year_cands = candidates[
    (candidates["year"] == selected_year)
    & (candidates["election_type"] == "UK national")
]

name_col = "name_canonical" if "name_canonical" in year_cands.columns else "name"

n_contests = len(year_contests)
n_seats    = int(year_contests["seats"].sum()) if year_contests["seats"].notna().any() else "?"
st.subheader(f"{n_contests} contests · {n_seats} seats")

OUTCOME_ORDER = ["Elected", "Uncontested", "Not Elected", "Withdrawn", "No Nomination"]

for _, contest in year_contests.iterrows():
    cands = year_cands[year_cands["contest_id"] == contest["contest_id"]].copy()

    seats   = int(contest["seats"]) if pd.notna(contest["seats"]) else "?"
    n_cands = len(cands[cands["outcome"] != "No Nomination"])
    votes   = int(contest["valid_votes"]) if pd.notna(contest["valid_votes"]) else None

    # Build expander label
    votes_str = f" · {votes:,} valid votes" if votes else ""
    label = f"**{contest['contest_name']}** — {seats} seat(s), {n_cands} candidate(s){votes_str}"

    with st.expander(label):
        if cands.empty:
            st.write("No candidate data.")
            continue

        # Sort by outcome priority then first preferences descending
        cands["_outcome_rank"] = cands["outcome"].apply(
            lambda o: OUTCOME_ORDER.index(o) if o in OUTCOME_ORDER else 99
        )
        cands = cands.sort_values(
            ["_outcome_rank", "first_preferences"], ascending=[True, False]
        )

        display_cands = cands[[name_col, "first_preferences", "outcome"]].rename(columns={
            name_col:            "Candidate",
            "first_preferences": "1st prefs",
            "outcome":           "Outcome",
        })
        display_cands["1st prefs"] = display_cands["1st prefs"].apply(
            lambda x: f"{int(x):,}" if pd.notna(x) else "—"
        )
        st.dataframe(display_cands.reset_index(drop=True), hide_index=True,
                     use_container_width=True)

# ---------------------------------------------------------------------------
# Source link at bottom
# ---------------------------------------------------------------------------

ucu_url = YEAR_URLS.get(selected_year)
if ucu_url:
    st.divider()
    st.caption(f"Source: [UCU election results page]({ucu_url})")
