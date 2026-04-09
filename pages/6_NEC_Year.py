"""UCU Elections — per-year NEC committee view."""

import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from utils import _csv_mtime, year_sort_key

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

# Previous year members (for "new?" flag)
prev_year = str(int(selected_year) - 1)
prev_members_set = set(
    membership.loc[membership["year"] == prev_year, "name_canonical"].unique()
)

year_members["_is_new"] = ~year_members["name_canonical"].isin(prev_members_set)

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
    """Render a membership table with Name (linked), Role, Sector, New? columns."""
    if df.empty:
        st.info("No members in this category.")
        return

    display = df[["name_canonical", "position", "sector", "_is_new"]].copy()
    display["Candidate"] = display["name_canonical"].apply(_make_link)
    display["New?"] = display["_is_new"].apply(lambda x: "New" if x else "")
    display = display.rename(columns={
        "position": "Role",
        "sector":   "Sector",
    })
    display = display[["Candidate", "Role", "Sector", "New?"]].reset_index(drop=True)

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
    officer_mask = year_members["role_type"].isin({"vp_chain", "officer", "trustee"})
    officer_df = year_members[officer_mask].copy()

    def _officer_sort(row: pd.Series) -> tuple:
        rt = row["role_type"]
        if rt == "vp_chain":
            return (0, _CHAIN_ORDER.get(row["position"], 99), row["sector"], row["name_canonical"])
        if rt == "officer":
            officer_rank = {"General Secretary": 0, "Honorary Treasurer": 1}
            return (1, officer_rank.get(row["position"], 99), row["sector"], row["name_canonical"])
        # trustee
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

