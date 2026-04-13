"""UCU Elections — per-year NEC committee view."""

import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent))

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import _csv_mtime, load_data, year_sort_key

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data" / "processed"


@st.cache_data
def load_membership(mtime: float) -> pd.DataFrame:
    path = DATA_DIR / "nec_membership.csv"
    return pd.read_csv(path, dtype={"year": str, "elected_year": str})


@st.cache_data
def load_stability(mtime: float) -> pd.DataFrame:
    path = DATA_DIR / "nec_stability.csv"
    return pd.read_csv(path, dtype={"year": str})


membership = load_membership(mtime=_csv_mtime())
stability  = load_stability(mtime=_csv_mtime())
contests, candidates, _ballots = load_data(mtime=_csv_mtime())

# Build quota lookup: (elected_year, name_canonical) → quota
# Uncontested members get quota = 0 (they cleared a bar of zero contested votes)
_cands_q = (
    candidates[
        candidates["outcome"].isin({"Elected", "Uncontested"})
        & candidates["election_type"].isin({"UK national", "casual vacancy"})
    ][["year", "name_canonical", "contest_id", "outcome"]]
    .merge(contests[["contest_id", "quota"]], on="contest_id", how="left")
    .copy()
)
_cands_q.loc[_cands_q["outcome"] == "Uncontested", "quota"] = 0.0
_cands_q["quota"] = pd.to_numeric(_cands_q["quota"], errors="coerce")
_quota_lookup: dict[tuple, float] = (
    _cands_q.dropna(subset=["name_canonical"])
    .set_index(["year", "name_canonical"])["quota"]
    .to_dict()
)

if membership.empty:
    st.warning("No NEC membership data found. Run `normalise.py` to generate it.")
    st.stop()

# ---------------------------------------------------------------------------
# Year selector
# ---------------------------------------------------------------------------

all_years = sorted(membership["year"].unique(), key=year_sort_key, reverse=True)

qp_year = st.query_params.get("year", all_years[0])
if qp_year not in all_years:
    qp_year = all_years[0]

selected_year = st.selectbox(
    "Committee year",
    all_years,
    index=all_years.index(qp_year),
)
if selected_year != qp_year:
    st.query_params["year"] = selected_year
    st.rerun()

# ---------------------------------------------------------------------------
# Members for selected year
# ---------------------------------------------------------------------------

year_members = membership[membership["year"] == selected_year].copy()

# Previous year members (for "new this year" flag)
prev_year = str(int(selected_year) - 1)
prev_members_set = set(
    membership.loc[membership["year"] == prev_year, "name_canonical"].unique()
)

# All members in any prior year (for "new ever" flag)
ever_before_set = set(
    membership.loc[membership["year"] < selected_year, "name_canonical"].unique()
)

year_members["_new_vs_prev"] = ~year_members["name_canonical"].isin(prev_members_set)
year_members["_new_ever"]    = ~year_members["name_canonical"].isin(ever_before_set)

year_members["quota"] = year_members.apply(
    lambda r: _quota_lookup.get((r["elected_year"], r["name_canonical"])), axis=1
)

# Stability row for this year
stab_row = stability[stability["year"] == selected_year]
total_members = len(year_members["name_canonical"].unique())
new_count     = int(stab_row["new_vs_prev"].iloc[0]) if not stab_row.empty else "?"

st.title(f"NEC {selected_year}")
st.markdown(f"**{total_members} members** | **{new_count} new this year**")

# ---------------------------------------------------------------------------
# VP chain sort order helper
# ---------------------------------------------------------------------------

_CHAIN_ORDER = {role: i for i, role in enumerate([
    "Vice-President", "President-elect", "President", "Immediate Past President",
])}

_ROLE_TYPE_ORDER = {
    "vp_chain":  0,
    "officer":   1,
    "uk_nec":    2,
    "regional":  3,
    "women":     4,
    "equality":  5,
    "trustee":   6,
    "other":     99,
}


def _make_link(name_canonical: str) -> str:
    return f"./Candidate?candidate={quote(str(name_canonical), safe=' ')}"


def _render_table(df: pd.DataFrame) -> None:
    """Render a membership table with Name (linked), Role, Sector, Status columns."""
    if df.empty:
        st.info("No members in this category.")
        return

    display = df[["name_canonical", "position", "sector", "_new_vs_prev", "_new_ever"]].copy()
    display["Candidate"] = display["name_canonical"].apply(_make_link)

    def _status(row: pd.Series) -> str:
        if row["_new_ever"]:
            return "New to NEC"
        if row["_new_vs_prev"]:
            return "Returning"
        return ""

    display["Status"] = display.apply(_status, axis=1)
    display = display.rename(columns={
        "position": "Role",
        "sector":   "Sector",
    })
    display = display[["Candidate", "Role", "Sector", "Status"]].reset_index(drop=True)

    st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Candidate": st.column_config.LinkColumn(
                "Name",
                display_text=r"candidate=(.+)",
            ),
        },
    )


_ROLE_COLORS = {
    "vp_chain": "#9467bd",
    "officer":  "#8c564b",
    "uk_nec":   "#1f77b4",
    "regional": "#2ca02c",
    "women":    "#e377c2",
    "equality": "#ff7f0e",
    "scotland": "#17becf",
}


def _render_quota_analysis(df: pd.DataFrame, label: str) -> None:
    """Dot plot of quota by member + majority mandate metric."""
    # Include members with quota data (notna); uncontested already = 0
    q_df = df[df["quota"].notna()].copy()
    n_missing = len(df) - len(q_df)
    if q_df.empty:
        st.caption("No quota data available for this committee.")
        return

    # --- Dot plot ---
    fig = go.Figure()
    for rt in sorted(q_df["role_type"].unique()):
        sub = q_df[q_df["role_type"] == rt].sort_values("quota")
        fig.add_trace(go.Scatter(
            x=sub["quota"],
            y=[rt] * len(sub),
            mode="markers",
            name=rt,
            marker=dict(size=13, color=_ROLE_COLORS.get(rt, "#7f7f7f"), opacity=0.75),
            text=sub["name_canonical"],
            hovertemplate="<b>%{text}</b><br>Quota: %{x:,.0f} votes<extra></extra>",
        ))
    fig.update_layout(
        xaxis=dict(rangemode="tozero", title="Votes (contest quota)"),
        yaxis=dict(title=None),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=max(200, len(q_df["role_type"].unique()) * 55 + 80),
        margin=dict(t=10, b=40, l=90, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Majority mandate ---
    sorted_q = sorted(q_df["quota"].tolist())
    n = len(sorted_q)
    majority_n = math.floor(n / 2) + 1
    majority_sum = sum(sorted_q[:majority_n])
    total_sum = sum(sorted_q)
    pct = 100 * majority_sum / total_sum if total_sum > 0 else 0.0
    missing_note = f" ({n_missing} member(s) excluded: no quota data.)" if n_missing else ""
    st.caption(
        f"**Majority mandate** — a controlling majority ({majority_n} of {n} members "
        f"with data) could be secured by members whose contests required a minimum of "
        f"**{majority_sum:,.0f}** votes combined — **{pct:.1f}%** of the "
        f"{total_sum:,.0f} total votes required across all {label} members with data."
        + missing_note
    )


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_officers, tab_fe, tab_he = st.tabs([
    "Officers & VP Chain", "FEC", "HEC",
])

# ---------------------------------------------------------------------------
# Officers & VP Chain tab
# ---------------------------------------------------------------------------

with tab_officers:
    # VP chain (all sectors) + officer + trustee
    officer_mask = year_members["role_type"].isin({"vp_chain", "officer"})
    officer_df = year_members[officer_mask].copy()

    def _officer_sort(row: pd.Series) -> tuple:
        rt = row["role_type"]
        if rt == "vp_chain":
            return (0, _CHAIN_ORDER.get(row["position"], 99), row["sector"], row["name_canonical"])
        if rt == "officer":
            officer_rank = {"General Secretary": 0, "Honorary Treasurer": 1}
            return (1, officer_rank.get(row["position"], 99), row["sector"], row["name_canonical"])
        return (2, 0, row["sector"], row["name_canonical"])

    if not officer_df.empty:
        officer_df["_sort"] = officer_df.apply(_officer_sort, axis=1)
        officer_df = officer_df.sort_values("_sort")
    _render_table(officer_df)

# ---------------------------------------------------------------------------
# FEC tab
# ---------------------------------------------------------------------------

with tab_fe:
    fe_mask = (
        (year_members["sector"] == "FE")
        & year_members["role_type"].isin({"vp_chain", "uk_nec", "regional", "women", "equality"})
        & ~((year_members["role_type"] == "vp_chain") & (year_members["position"] == "President"))
    )
    fe_df = year_members[fe_mask].copy()

    def _fe_sort(row: pd.Series) -> tuple:
        rt = row["role_type"]
        if rt == "vp_chain":
            return (0, _CHAIN_ORDER.get(row["position"], 99), row["name_canonical"])
        if rt == "uk_nec":
            return (1, 0, row["name_canonical"])
        if rt == "regional":
            return (2, row["position"], row["name_canonical"])
        if rt == "women":
            return (3, row["position"], row["name_canonical"])
        return (99, row["position"], row["name_canonical"])

    if not fe_df.empty:
        fe_df["_sort"] = fe_df.apply(_fe_sort, axis=1)
        fe_df = fe_df.sort_values("_sort")
    _render_table(fe_df)
    st.divider()
    _render_quota_analysis(fe_df, "FEC")

# ---------------------------------------------------------------------------
# HEC tab
# ---------------------------------------------------------------------------

with tab_he:
    he_mask = (
        (year_members["sector"] == "HE")
        & year_members["role_type"].isin({"vp_chain", "uk_nec", "regional", "women", "equality"})
        & ~((year_members["role_type"] == "vp_chain") & (year_members["position"] == "President"))
    )
    he_df = year_members[he_mask].copy()

    def _he_sort(row: pd.Series) -> tuple:
        rt = row["role_type"]
        if rt == "vp_chain":
            return (0, _CHAIN_ORDER.get(row["position"], 99), row["name_canonical"])
        if rt == "uk_nec":
            return (1, 0, row["name_canonical"])
        if rt == "regional":
            return (2, row["position"], row["name_canonical"])
        if rt == "women":
            return (3, row["position"], row["name_canonical"])
        return (99, row["position"], row["name_canonical"])

    if not he_df.empty:
        he_df["_sort"] = he_df.apply(_he_sort, axis=1)
        he_df = he_df.sort_values("_sort")
    _render_table(he_df)
    st.divider()
    _render_quota_analysis(he_df, "HEC")

