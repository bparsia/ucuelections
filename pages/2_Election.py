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

contests, candidates, ballots = load_data(mtime=_csv_mtime())

# STV final-vote lookup: max-round votes per (contest_id, name)
@st.cache_data
def load_final_votes(mtime: float) -> dict:
    path = Path(__file__).parent.parent / "data" / "processed" / "stv_rounds.csv"
    rounds = pd.read_csv(path, dtype={"year": str})
    rounds["round"] = rounds["round"].astype(int)
    idx = rounds.groupby(["contest_id", "name"])["round"].idxmax()
    last = rounds.loc[idx].set_index(["contest_id", "name"])["votes"]
    return last.to_dict()

_final_votes = load_final_votes(mtime=_csv_mtime())

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

col_hdr, col_btns = st.columns([3, 1])
col_hdr.subheader(f"{n_contests} contests · {n_seats} seats")
with col_btns:
    st.write("")   # vertical spacing
    bc1, bc2 = st.columns(2)
    if bc1.button("Expand all", use_container_width=True):
        st.session_state["expanders_open"] = True
    if bc2.button("Collapse all", use_container_width=True):
        st.session_state["expanders_open"] = False

_expanded = st.session_state.get("expanders_open", False)

OUTCOME_ORDER = ["Elected", "Uncontested", "Not Elected", "Withdrawn", "No Nomination"]

for _, contest in year_contests.iterrows():
    cands = year_cands[year_cands["contest_id"] == contest["contest_id"]].copy()

    seats   = int(contest["seats"]) if pd.notna(contest["seats"]) else "?"
    n_cands = len(cands[cands["outcome"] != "No Nomination"])
    votes   = int(contest["valid_votes"]) if pd.notna(contest["valid_votes"]) else None
    quota   = float(contest["quota"]) if "quota" in contest.index and pd.notna(contest["quota"]) else None

    # Build expander label
    votes_str = f" · {votes:,} valid votes" if votes else ""
    quota_str = (" · quota " + f"{quota:,.2f}".rstrip("0").rstrip(".")) if quota else ""
    label = f"**{contest['contest_name']}** — {seats} seat(s), {n_cands} candidate(s){votes_str}{quota_str}"

    with st.expander(label, expanded=_expanded):
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

        display_cands = cands[[name_col, "first_preferences", "outcome", "contest_id", "name"]].copy()
        display_cands["Final votes"] = display_cands.apply(
            lambda r: _final_votes.get((r["contest_id"], r["name"])), axis=1
        )
        display_cands = display_cands.rename(columns={
            name_col:            "Candidate",
            "first_preferences": "1st prefs",
            "outcome":           "Outcome",
        })
        display_cands["1st prefs"] = display_cands["1st prefs"].apply(
            lambda x: f"{int(x):,}" if pd.notna(x) else "—"
        )
        display_cands["Final votes"] = display_cands["Final votes"].apply(
            lambda x: f"{x:,.2f}".rstrip("0").rstrip(".") if pd.notna(x) else "—"
        )
        # Hide Final votes column if all values are "—" (no STV data)
        cols_to_show = ["Candidate", "1st prefs"]
        if display_cands["Final votes"].ne("—").any():
            cols_to_show.append("Final votes")
        cols_to_show.append("Outcome")
        st.dataframe(display_cands[cols_to_show].reset_index(drop=True), hide_index=True,
                     use_container_width=True)

# ---------------------------------------------------------------------------
# Source link at bottom
# ---------------------------------------------------------------------------

ucu_url = YEAR_URLS.get(selected_year)
if ucu_url:
    st.divider()
    st.caption(f"Source: [UCU election results page]({ucu_url})")
