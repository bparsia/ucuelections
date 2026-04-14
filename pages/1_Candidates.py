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

# Merge in contest quota for ratio calculation
winners = winners.merge(
    contests[["contest_id", "quota"]],
    on="contest_id", how="left",
)

# UK-wide quota lookup by (year, sector) from national FE/HE seats
_uk_quota: dict[tuple, float] = {}
for _, row in contests[
    contests["position"].isin({"UK NEC Members, FE", "UK NEC Members, HE"})
].iterrows():
    if pd.notna(row["quota"]):
        sector = "FE" if "FE" in row["position"] else "HE"
        _uk_quota[(str(row["year"]), sector)] = float(row["quota"])

def _detect_sector(pos: str) -> str | None:
    if not isinstance(pos, str):
        return None
    if ", FE" in pos or pos.endswith("FE"):
        return "FE"
    if ", HE" in pos or pos.endswith("HE"):
        return "HE"
    return None

winners["sector"] = winners["position"].apply(_detect_sector)


def _fmt_winner_row(df: pd.DataFrame, show_uk_ratio: bool = False) -> pd.DataFrame:
    cols = [name_col, "Year", "position", "first_preferences", "final_votes"]
    if show_uk_ratio:
        cols += ["sector"]
    out = (
        df[cols]
        .rename(columns={
            name_col:   "Candidate",
            "position": "Contest",
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
    if show_uk_ratio:
        def _ratio(r):
            fv = df.iloc[r.name]["final_votes"]
            yr = df.iloc[r.name]["year"]
            sec = df.iloc[r.name]["sector"]
            uk_q = _uk_quota.get((yr, sec))
            if pd.notna(fv) and uk_q:
                return f"{fv / uk_q:.2f}×"
            return "—"
        out["vs UK quota"] = out.apply(_ratio, axis=1)
        out = out.drop(columns=["sector"])
    out["1st prefs"] = out["1st prefs"].apply(lambda x: f"{int(x):,}" if pd.notna(x) else "—")
    return out


st.subheader("Top 20 vote-getters (winners, final votes)")
top = _fmt_winner_row(winners.nlargest(20, "final_votes"))
top.index += 1
st.dataframe(top, use_container_width=True)

st.subheader("Bottom 20 vote-getters (winners, final votes)")
st.caption(
    "Elected candidates with the lowest final vote tally — excludes uncontested seats. "
    "Split by sector; **vs UK quota** = winner's final votes ÷ that year's UK-wide FE/HE NEC seat quota."
)
contested_winners = winners[
    (winners["outcome"] == "Elected") & winners["sector"].notna()
].dropna(subset=["final_votes"])

tab_fe, tab_he = st.tabs(["FE", "HE"])
with tab_fe:
    fe_bot = _fmt_winner_row(
        contested_winners[contested_winners["sector"] == "FE"].nsmallest(20, "final_votes"),
        show_uk_ratio=True,
    )
    fe_bot.index += 1
    st.dataframe(fe_bot, use_container_width=True)
with tab_he:
    he_bot = _fmt_winner_row(
        contested_winners[contested_winners["sector"] == "HE"].nsmallest(20, "final_votes"),
        show_uk_ratio=True,
    )
    he_bot.index += 1
    st.dataframe(he_bot, use_container_width=True)

# ---------------------------------------------------------------------------
# Uncontested seats
# ---------------------------------------------------------------------------

st.subheader("Uncontested seats")
st.caption(
    "Seats where only one candidate stood — returned without a vote. "
    "Excludes no-nomination contests (seat existed but nobody stood)."
)

all_unc = candidates[candidates["outcome"] == "Uncontested"].copy()

def _seat_category(row) -> str:
    if row["election_type"] == "Scotland":
        return "Scotland"
    pos = row["position"]
    if not isinstance(pos, str):
        return "Other"
    if "Representatives of" in pos:
        return "Equality"
    if "NEC Members" in pos:
        return "Regional"
    if "Vice-President" in pos or "President" in pos:
        return "VP chain"
    return "Other"

all_unc["Category"] = all_unc.apply(_seat_category, axis=1)
all_unc["Year"] = all_unc["year"]

# Summary by year and category
unc_summary = (
    all_unc.groupby(["Year", "Category"])
    .size()
    .reset_index(name="Uncontested seats")
    .sort_values(["Year", "Category"])
)

col_chart, col_table = st.columns([2, 1])

with col_chart:
    import plotly.graph_objects as go
    categories = sorted(all_unc["Category"].unique())
    years = sorted(all_unc["Year"].unique(), key=year_sort_key)
    CAT_COLOURS = {
        "Equality": "#ff7f0e",
        "Regional": "#2ca02c",
        "Scotland": "#17becf",
        "VP chain": "#9467bd",
        "Other":    "#7f7f7f",
    }
    fig_unc = go.Figure()
    for cat in categories:
        sub = unc_summary[unc_summary["Category"] == cat]
        fig_unc.add_trace(go.Bar(
            x=sub["Year"],
            y=sub["Uncontested seats"],
            name=cat,
            marker_color=CAT_COLOURS.get(cat, "#7f7f7f"),
        ))
    fig_unc.update_layout(
        barmode="stack",
        xaxis=dict(type="category", title=None),
        yaxis=dict(rangemode="tozero", title="Seats"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=320,
        margin=dict(t=10, b=40, l=40, r=10),
    )
    st.plotly_chart(fig_unc, use_container_width=True)

with col_table:
    unc_by_cat = (
        all_unc.groupby("Category")
        .size()
        .reset_index(name="Total")
        .sort_values("Total", ascending=False)
    )
    st.dataframe(unc_by_cat, hide_index=True, use_container_width=True)

# Full list
unc_display = (
    all_unc[["Year", "Category", "position", "name_canonical", "election_type"]]
    .rename(columns={
        "position":       "Contest",
        "name_canonical": "Candidate",
        "election_type":  "Election",
    })
    .sort_values(["Year", "Category", "Contest"])
    .reset_index(drop=True)
)
unc_display["Candidate"] = unc_display["Candidate"].apply(
    lambda n: f"[{n}](/Candidate?candidate={quote(str(n))})"
)

with st.expander("Full list of uncontested returns"):
    header = "| " + " | ".join(unc_display.columns) + " |"
    sep    = "| " + " | ".join("---" for _ in unc_display.columns) + " |"
    rows   = "\n".join(
        "| " + " | ".join(str(v) for v in row) + " |"
        for row in unc_display.itertuples(index=False)
    )
    st.markdown(f"{header}\n{sep}\n{rows}")

# Repeat uncontested winners
repeat_unc = (
    all_unc.groupby("name_canonical")
    .agg(
        Times=("year", "count"),
        Years=("year", lambda s: ", ".join(sorted(s, key=year_sort_key))),
        Contest=("position", "first"),
    )
    .reset_index()
    .rename(columns={"name_canonical": "Candidate"})
    .query("Times > 1")
    .sort_values("Times", ascending=False)
    .reset_index(drop=True)
)
if not repeat_unc.empty:
    st.caption("**Repeat uncontested returns**")
    st.dataframe(repeat_unc, hide_index=True, use_container_width=True)

# No-nomination contests
no_nom = candidates[candidates["outcome"] == "No Nomination"].copy()
if not no_nom.empty:
    no_nom_display = (
        no_nom[["year", "position", "election_type"]]
        .drop_duplicates()
        .rename(columns={"year": "Year", "position": "Contest", "election_type": "Election"})
        .sort_values("Year")
        .reset_index(drop=True)
    )
    with st.expander(f"No-nomination contests ({len(no_nom_display)} — seat existed, nobody stood)"):
        st.dataframe(no_nom_display, hide_index=True, use_container_width=True)

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
