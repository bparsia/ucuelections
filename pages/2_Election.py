"""UCU Elections — per-year election report page."""

import re
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
# Year selection
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
# Contest data for selected year
# ---------------------------------------------------------------------------

year_contests = contests[
    (contests["year"] == selected_year)
    & (contests["election_type"] == "UK national")
].copy()

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
    st.write("")
    bc1, bc2 = st.columns(2)
    if bc1.button("Expand all", use_container_width=True):
        st.session_state["expanders_open"] = True
    if bc2.button("Collapse all", use_container_width=True):
        st.session_state["expanders_open"] = False

_expanded = st.session_state.get("expanders_open", False)

# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

OFFICER_POSITIONS = {
    "General Secretary", "Honorary Treasurer",
    "Vice-President, FE", "Vice-President, HE",
    "President-elect, FE", "President-elect, HE",
    "Trustees",
}
OFFICER_RANK = {p: i for i, p in enumerate([
    "General Secretary",
    "Vice-President, FE", "Vice-President, HE",
    "President-elect, FE", "President-elect, HE",
    "Honorary Treasurer",
    "Trustees",
])}

FE_UKWIDE_POSITIONS = {"UK NEC Members, FE"}
HE_UKWIDE_POSITIONS = {"UK NEC Members, HE"}
SCOTLAND_POSITIONS  = {"UCU Scotland President", "UCU Scotland Honorary Secretary"}
WALES_VP_POSITION   = "Vice-President, UCU Wales"


def _is_fe_regional(pos: str) -> bool:
    if not isinstance(pos, str) or not pos.startswith("NEC Members,"):
        return False
    return ", FE" in pos or "Vice-President UCU Wales" in pos


def _is_he_regional(pos: str) -> bool:
    if not isinstance(pos, str):
        return False
    if pos.startswith("NEC Members,") and ", HE" in pos:
        return True
    return pos in SCOTLAND_POSITIONS or pos == WALES_VP_POSITION


def _is_equality(pos: str) -> bool:
    return isinstance(pos, str) and pos.startswith("Representatives of")


def _classify(pos: str) -> str:
    if pos in OFFICER_POSITIONS:        return "officer"
    if pos in FE_UKWIDE_POSITIONS:      return "fe_ukwide"
    if pos in HE_UKWIDE_POSITIONS:      return "he_ukwide"
    if _is_fe_regional(pos):            return "fe_regional"
    if _is_he_regional(pos):            return "he_regional"
    if _is_equality(pos):               return "equality"
    return "other"


def _short_label(pos: str) -> str:
    """Region name for display within an NEC FE/HE tab."""
    if pos.startswith("NEC Members, "):
        inner = pos[len("NEC Members, "):]
        inner = re.sub(r",\s*(FE|HE)\b", "", inner).strip()
        return inner
    return pos


def _region_sort_key(pos: str) -> str:
    if pos in SCOTLAND_POSITIONS:
        return ("Scotland", pos)
    if pos == WALES_VP_POSITION:
        return ("Wales", pos)
    if pos.startswith("NEC Members, "):
        inner = pos[len("NEC Members, "):]
        region = inner.split(",")[0].strip()
        return (region, pos)
    return (pos, pos)


year_contests["_group"] = year_contests["position"].fillna("").apply(_classify)

# ---------------------------------------------------------------------------
# Contest renderer
# ---------------------------------------------------------------------------

OUTCOME_ORDER = ["Elected", "Uncontested", "Not Elected", "Withdrawn", "No Nomination"]


def render_contest(contest, short_label: bool = False):
    cands = year_cands[year_cands["contest_id"] == contest["contest_id"]].copy()

    seats   = int(contest["seats"])      if pd.notna(contest.get("seats"))       else "?"
    n_cands = len(cands[cands["outcome"] != "No Nomination"])
    votes   = int(contest["valid_votes"]) if pd.notna(contest.get("valid_votes")) else None
    quota   = (
        float(contest["quota"])
        if "quota" in contest.index and pd.notna(contest.get("quota"))
        else None
    )

    label_name = _short_label(contest["position"]) if short_label else contest["position"]
    votes_str  = f" · {votes:,} valid votes" if votes else ""
    quota_str  = (" · quota " + f"{quota:,.2f}".rstrip("0").rstrip(".")) if quota else ""
    label      = f"**{label_name}** — {seats} seat(s), {n_cands} candidate(s){votes_str}{quota_str}"

    with st.expander(label, expanded=_expanded):
        if cands.empty:
            st.write("No candidate data.")
            return

        cands["_outcome_rank"] = cands["outcome"].apply(
            lambda o: OUTCOME_ORDER.index(o) if o in OUTCOME_ORDER else 99
        )
        cands = cands.sort_values(["_outcome_rank", "first_preferences"], ascending=[True, False])

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
        cols_to_show = ["Candidate", "1st prefs"]
        if display_cands["Final votes"].ne("—").any():
            cols_to_show.append("Final votes")
        cols_to_show.append("Outcome")
        st.dataframe(
            display_cands[cols_to_show].reset_index(drop=True),
            hide_index=True,
            use_container_width=True,
        )
        # TODO: Sankey diagram of STV flow


def render_group(df: pd.DataFrame, short_label: bool = False):
    if df.empty:
        return
    for _, contest in df.iterrows():
        render_contest(contest, short_label=short_label)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_officers, tab_fe, tab_he, tab_eq = st.tabs([
    "Officers & Trustees", "NEC FE", "NEC HE", "Equality Seats",
])

# --- Officers & Trustees ---
with tab_officers:
    officers = year_contests[year_contests["_group"] == "officer"].copy()
    officers["_rank"] = officers["position"].map(lambda p: OFFICER_RANK.get(p, 99))
    render_group(officers.sort_values("_rank"))
    if officers.empty:
        st.info("No officer or trustee contests this year.")

# --- NEC FE ---
with tab_fe:
    fe_wide     = year_contests[year_contests["_group"] == "fe_ukwide"]
    fe_regional = year_contests[year_contests["_group"] == "fe_regional"].copy()
    fe_regional["_sort"] = fe_regional["position"].apply(
        lambda p: _region_sort_key(p)
    )
    fe_regional = fe_regional.sort_values("_sort")

    if not fe_wide.empty:
        st.subheader("UK-Wide")
        render_group(fe_wide)
    if not fe_regional.empty:
        st.subheader("Regions & Nations")
        render_group(fe_regional, short_label=True)
    if fe_wide.empty and fe_regional.empty:
        st.info("No FE NEC contests this year.")

# --- NEC HE ---
with tab_he:
    he_wide     = year_contests[year_contests["_group"] == "he_ukwide"]
    he_regional = year_contests[year_contests["_group"] == "he_regional"].copy()
    he_regional["_sort"] = he_regional["position"].apply(
        lambda p: _region_sort_key(p)
    )
    he_regional = he_regional.sort_values("_sort")
    he_other    = year_contests[year_contests["position"] == "UCU Scotland NEC Members, HE"]

    if not he_wide.empty:
        st.subheader("UK-Wide")
        render_group(he_wide)
    if not he_regional.empty:
        st.subheader("Regions & Nations")
        render_group(he_regional, short_label=True)
    if not he_other.empty:
        st.subheader("Other")
        render_group(he_other)
    if he_wide.empty and he_regional.empty and he_other.empty:
        st.info("No HE NEC contests this year.")

# --- Equality Seats ---
with tab_eq:
    equality = year_contests[year_contests["_group"] == "equality"]
    render_group(equality.sort_values("position"))
    if equality.empty:
        st.info("No equality seat contests this year.")

# --- Ungrouped safety net ---
ungrouped = year_contests[
    (year_contests["_group"] == "other")
    & (year_contests["position"] != "UCU Scotland NEC Members, HE")
]
if not ungrouped.empty:
    st.divider()
    st.caption("**Ungrouped contests**")
    render_group(ungrouped)

# ---------------------------------------------------------------------------
# Source link
# ---------------------------------------------------------------------------

ucu_url = YEAR_URLS.get(selected_year)
if ucu_url:
    st.divider()
    st.caption(f"Source: [UCU election results page]({ucu_url})")
