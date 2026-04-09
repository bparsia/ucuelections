"""UCU Elections — per-year election report page."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.graph_objects as go
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


@st.cache_data
def load_rounds(mtime: float) -> pd.DataFrame:
    path = Path(__file__).parent.parent / "data" / "processed" / "stv_rounds.csv"
    return pd.read_csv(path, dtype={"year": str})


_rounds = load_rounds(mtime=_csv_mtime())

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

# ---------------------------------------------------------------------------
# Sankey builder
# ---------------------------------------------------------------------------

_OUTCOME_COLORS = {
    "Elected":      "rgba(0,150,50,0.85)",
    "Uncontested":  "rgba(0,150,50,0.85)",
    "Not Elected":  "rgba(200,60,60,0.85)",
    "Withdrawn":    "rgba(160,100,40,0.85)",
}
_DEFAULT_NODE_COLOR = "rgba(100,100,200,0.85)"


def build_stv_sankey(
    contest_id: str,
    rounds_df: pd.DataFrame,
    contest_cands: pd.DataFrame,
) -> go.Figure | None:
    """
    Build a Plotly Sankey of STV vote transfers for one contest.

    Each elimination event creates links from the eliminated candidate(s)
    to the candidates who received their transfers (proportionally when
    multiple candidates are eliminated in the same round).
    Returns None when there is no transfer data to show.
    """
    cdata = rounds_df[rounds_df["contest_id"] == contest_id].copy()
    if cdata.empty:
        return None

    rnd_vals = sorted(cdata["round"].unique())
    if len(rnd_vals) < 2:
        return None

    # (name, round) → row
    lookup: dict[tuple, pd.Series] = {
        (row["name"], row["round"]): row
        for _, row in cdata.iterrows()
    }

    # Outcome and canonical name per raw name
    outcome_map:   dict[str, str] = {}
    canonical_map: dict[str, str] = {}
    if not contest_cands.empty:
        outcome_map   = dict(zip(contest_cands["name"], contest_cands["outcome"]))
        display_col   = "name_canonical" if "name_canonical" in contest_cands.columns else "name"
        canonical_map = dict(zip(contest_cands["name"], contest_cands[display_col]))

    cand_names = list(cdata["name"].unique())

    # Round each candidate was first marked eliminated
    elim_round: dict[str, int] = {}
    for name in cand_names:
        first_elim = (
            cdata[(cdata["name"] == name) & (cdata["eliminated"] == True)]
            ["round"].min()
        )
        if pd.notna(first_elim):
            elim_round[name] = int(first_elim)

    # Group newly eliminated candidates by their elimination round
    elim_by_round: dict[int, list[str]] = {}
    for name, r in elim_round.items():
        elim_by_round.setdefault(r, []).append(name)

    # Node labels (canonical names) and colours
    node_labels = [canonical_map.get(n, n) for n in cand_names] + ["Non-transferable"]
    node_idx    = {n: i for i, n in enumerate(cand_names)}
    nt_idx      = len(cand_names)

    def _node_color(name: str) -> str:
        return _OUTCOME_COLORS.get(outcome_map.get(name, ""), _DEFAULT_NODE_COLOR)

    node_colors = [_node_color(n) for n in cand_names] + ["rgba(180,180,180,0.85)"]

    sources:     list[int]   = []
    targets:     list[int]   = []
    values:      list[float] = []
    link_colors: list[str]   = []

    for r_idx, r in enumerate(rnd_vals):
        if r_idx == 0:
            continue

        r_prev     = rnd_vals[r_idx - 1]
        newly_elim = elim_by_round.get(r, [])

        # Source votes: newly eliminated candidates (their last active votes)
        source_votes: dict[str, float] = {}
        for name in newly_elim:
            row = lookup.get((name, r_prev))
            if row is not None and pd.notna(row["votes"]) and row["votes"] > 0:
                source_votes[name] = float(row["votes"])

        # Gainers by actual delta; also detect surplus sources (active candidates
        # whose vote count decreased — elected and distributing surplus).
        # Using deltas avoids artefacts in the transfer column (e.g. an elected
        # candidate's full tally re-stamped as a transfer in later rounds).
        gainers: dict[str, float] = {}
        for name in cand_names:
            row      = lookup.get((name, r))
            row_prev = lookup.get((name, r_prev))
            if (row is None or row_prev is None
                    or pd.isna(row.get("votes")) or pd.isna(row_prev.get("votes"))
                    or row.get("eliminated")):
                continue
            delta = float(row["votes"]) - float(row_prev["votes"])
            if delta > 0:
                gainers[name] = delta
            elif delta < 0:
                source_votes[name] = source_votes.get(name, 0) + abs(delta)

        total_available = sum(source_votes.values())
        if total_available <= 0:
            continue
        total_gains       = sum(gainers.values())
        non_transferable  = max(0.0, total_available - total_gains)

        for src_name, src_v in source_votes.items():
            frac      = src_v / total_available
            link_col  = _node_color(src_name).replace("0.85", "0.35")

            for gainer, gain in gainers.items():
                flow = round(gain * frac, 2)
                if flow > 0:
                    sources.append(node_idx[src_name])
                    targets.append(node_idx[gainer])
                    values.append(flow)
                    link_colors.append(link_col)

            nt_flow = round(non_transferable * frac, 2)
            if nt_flow > 0.01:
                sources.append(node_idx[src_name])
                targets.append(nt_idx)
                values.append(nt_flow)
                link_colors.append("rgba(180,180,180,0.25)")

    if not sources:
        return None

    height = max(300, min(650, len(cand_names) * 28 + 80))

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(
            label=node_labels,
            color=node_colors,
            pad=12,
            thickness=16,
            line=dict(color="white", width=0.5),
        ),
        link=dict(
            source=sources,
            target=targets,
            value=values,
            color=link_colors,
        ),
    ))
    fig.update_layout(
        height=height,
        margin=dict(l=5, r=5, t=10, b=5),
        font=dict(size=11),
    )
    return fig


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
            lambda r: None if r["outcome"] == "Withdrawn"
            else _final_votes.get((r["contest_id"], r["name"])), axis=1
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

        if contest.get("has_stv_rounds"):
            fig = build_stv_sankey(contest["contest_id"], _rounds, cands)
            if fig:
                st.plotly_chart(fig, use_container_width=True)


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
