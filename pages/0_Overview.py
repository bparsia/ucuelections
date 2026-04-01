"""UCU Elections — Overview page (turnout)."""

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

all_years = sorted(contests["year"].unique(), key=year_sort_key)

# ---------------------------------------------------------------------------
# Gross stats table (UK national elections only)
# ---------------------------------------------------------------------------

uk_contests   = contests[contests["election_type"] == "UK national"]
uk_candidates = candidates[candidates["election_type"] == "UK national"]

stats = (
    uk_contests
    .groupby("year", sort=False)
    .agg(seats=("seats", "sum"))
    .join(
        uk_candidates.groupby("year").agg(
            candidates=("name", "count"),
            elected=("outcome", lambda x: x.isin({"Elected", "Uncontested"}).sum()),
            uncontested=("outcome", lambda x: (x == "Uncontested").sum()),
        )
    )
    .reset_index()
)

# Seats in no-nomination contests
_no_nom_cids = (
    uk_candidates[uk_candidates["outcome"] == "No Nomination"]["contest_id"].unique()
)
_no_nom_seats = (
    uk_contests[uk_contests["contest_id"].isin(_no_nom_cids)]
    .groupby("year")["seats"]
    .sum()
    .rename("no_nom_seats")
)
stats = stats.join(_no_nom_seats, on="year")

# Attach ballot stats for each type
clean_uk = ballots[
    (~ballots["suspect"].astype(bool))
    & (ballots["election_type"] == "UK national")
]
for btype in ("national", "HE", "FE"):
    sub = (
        clean_uk[clean_uk["ballot_type"] == btype]
        [["year", "eligible_voters", "votes_cast", "turnout_pct"]]
        .rename(columns={
            "eligible_voters": f"eligible_{btype}",
            "votes_cast":      f"cast_{btype}",
            "turnout_pct":     f"turnout_{btype}",
        })
    )
    stats = stats.merge(sub, on="year", how="left")

# Append rows for standalone GS elections
gs_contests   = contests[contests["election_type"] == "general secretary"]
gs_candidates = candidates[candidates["election_type"] == "general secretary"]
for yr in GS_STANDALONE:
    gs_yr_key = yr + "_gs"
    _seats     = gs_contests[gs_contests["year"] == yr]["seats"].sum()
    _gs_cands_yr = gs_candidates[gs_candidates["year"] == yr]
    _contest_counts = _gs_cands_yr.groupby("contest_id").size()
    if not _contest_counts.empty:
        _main_id     = _contest_counts.idxmax()
        _gs_cands_yr = _gs_cands_yr[_gs_cands_yr["contest_id"] == _main_id]
    _elected = (_gs_cands_yr["outcome"] == "Elected").sum()
    _ballot  = ballots[
        (ballots["election_type"] == "general secretary")
        & (ballots["ballot_type"] == "national")
        & (ballots["year"] == yr)
    ]
    _elig = _ballot["eligible_voters"].max() if not _ballot.empty else pd.NA
    _cast = _ballot["votes_cast"].max()      if not _ballot.empty else pd.NA
    _tpct = _ballot["turnout_pct"].max()     if not _ballot.empty else pd.NA
    gs_row = pd.DataFrame([{
        "year": gs_yr_key,
        "seats": pd.array([int(_seats)], dtype="Int64")[0],
        "candidates": len(_gs_cands_yr),
        "elected": _elected,
        "eligible_national": _elig,
        "cast_national": _cast,
        "turnout_national": _tpct,
    }])
    stats = pd.concat([stats, gs_row], ignore_index=True)

stats = stats.sort_values("year", key=lambda s: s.map(year_sort_key), ascending=False)
stats["seats"] = stats["seats"].astype("Int64")

# ---------------------------------------------------------------------------
# Turnout chart data
# ---------------------------------------------------------------------------

clean_ballots = ballots[
    (~ballots["suspect"].astype(bool))
    & (ballots["election_type"] == "UK national")
]

_standalone_gs = (
    ballots[
        (ballots["election_type"] == "general secretary")
        & (ballots["ballot_type"] == "national")
        & (ballots["year"].isin(GS_STANDALONE))
    ]
    .copy()
)
_standalone_gs["year"] = _standalone_gs["year"] + "_gs"
clean_ballots = pd.concat([clean_ballots, _standalone_gs], ignore_index=True)

chart_years = sorted(clean_ballots["year"].unique(), key=year_sort_key)

BALLOT_COLOURS = {
    "national": "#1f77b4",
    "HE":       "#ff7f0e",
    "FE":       "#2ca02c",
}

# ---------------------------------------------------------------------------
# Plenary dataset stats (all election types)
# ---------------------------------------------------------------------------

_total_elections = len(contests)
_total_seats     = int(contests["seats"].sum())
_total_cands     = len(candidates)
_distinct_cands  = (
    candidates["name_canonical"].str.strip().str.lower().nunique()
    if "name_canonical" in candidates.columns
    else candidates["name"].str.strip().str.lower().nunique()
)
_total_winners = candidates["outcome"].isin({"Elected", "Uncontested"}).sum()
_year_min      = min(all_years, key=year_sort_key)
_year_max      = max(all_years, key=year_sort_key)
_PLENARY = (
    f"The dataset covers {_total_elections:,} contests across "
    f"{display_year(_year_min)}–{display_year(_year_max)}, "
    f"with {_total_seats:,} seats at stake, "
    f"{_total_cands:,} candidate appearances by {_distinct_cands:,} distinct names, "
    f"and {_total_winners:,} winners."
)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

st.title("UCU Elections — Overview")
st.info(_PLENARY)
st.markdown("""
This is an early version of a UCU election data explorer vibe/spec coded by Bijan Parsia using Claude CLI (AI tool). The repository isn't really in a [great state](https://github.com/bparsia/ucuelections) but it's probably usable.

The scripts scrape the results from various UCU pages as a mix of HTML and (usually but not always) text PDFs. The format is...not entirely regular, so weirdnesses happen.

At the moment, I just share the overall turn out results, which I think are interesting. There may still be errors. Drill downs into each election coming soon.

One personal takeaway is that turnout is low and not obviously correlated with various supposed turn out lowering events I've seen hypothesized (including by me).

The one exception (as I get all the data in) is the stretch from 2018-2020. USS + the end of the Hunt era may have produced a low then
a bump? (But then what about the low in 2016?! Smells like wish-casting!)

Oh, and, we 100% need GTVO in FE even more than in HE.  """)

# --- Turnout chart -----------------------------------------------------------
st.subheader("Turnout by ballot, 2009–2026")
st.caption(
    "Suspect or unclassifiable rows excluded (see DATA_ISSUES.md). "
    "Gaps = years with no parseable scrutineer report. "
    "★ = year with concurrent General Secretary election. "
    "2019 GS = standalone casual-vacancy GS election (separate ballot)."
)

chart_labels = [display_year(y) for y in chart_years]
year_pos = {y: i for i, y in enumerate(chart_years)}

fig = go.Figure()

for btype, colour in BALLOT_COLOURS.items():
    sub = (
        clean_ballots[clean_ballots["ballot_type"] == btype]
        .copy()
        .assign(_order=lambda df: df["year"].map(year_sort_key))
        .sort_values("_order")
        .dropna(subset=["turnout_pct"])
    )
    labels = [display_year(y) for y in sub["year"]]
    fig.add_trace(go.Scatter(
        x=[year_pos[y] for y in sub["year"]],
        y=sub["turnout_pct"].tolist(),
        mode="lines+markers",
        name=btype.capitalize(),
        line=dict(color=colour, width=2),
        marker=dict(size=7),
        connectgaps=False,
        customdata=sub[["eligible_voters", "votes_cast"]].values,
        text=labels,
        hovertemplate=(
            f"<b>%{{text}}</b> — {btype.capitalize()} ballot<br>"
            "Turnout: <b>%{y:.1f}%</b><br>"
            "Eligible: %{customdata[0]:,.0f}<br>"
            "Votes cast: %{customdata[1]:,.0f}"
            "<extra></extra>"
        ),
    ))

# GS election annotations
nat_sub = clean_ballots[clean_ballots["ballot_type"] == "national"].set_index("year")
gs_annotation_years = GS_CONCURRENT | {y + "_gs" for y in GS_STANDALONE}
for yr in gs_annotation_years:
    if yr in nat_sub.index and pd.notna(nat_sub.loc[yr, "turnout_pct"]):
        fig.add_annotation(
            x=year_pos[yr],
            y=nat_sub.loc[yr, "turnout_pct"],
            text="★ GS",
            showarrow=True,
            arrowhead=2,
            arrowsize=0.8,
            ax=0,
            ay=-28,
            font=dict(size=11, color=BALLOT_COLOURS["national"]),
        )

fig.update_layout(
    xaxis=dict(
        tickmode="array",
        tickvals=list(range(len(chart_years))),
        ticktext=chart_labels,
        tickangle=-45,
    ),
    xaxis_title=None,
    yaxis_title="Turnout (%)",
    yaxis=dict(ticksuffix="%", rangemode="tozero"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    height=420,
    hovermode="closest",
    margin=dict(t=20, b=60),
)
st.plotly_chart(fig, use_container_width=True)

# --- Gross stats table -------------------------------------------------------
st.subheader("UK national elections — summary by year")

def _fmt_int(x) -> str:
    return f"{int(x):,}" if pd.notna(x) else "—"

def _fmt_sector(nat, fe, he, fmt) -> str:
    main  = fmt(nat)
    parts = "/".join(fmt(v) for v in (fe, he) if pd.notna(v))
    return f"{main} ({parts})" if parts else main

display = stats.rename(columns={
    "year": "Year", "seats": "Seats",
    "candidates": "Candidates", "elected": "Elected",
    "uncontested": "Uncontested", "no_nom_seats": "NoNomSeats",
}).copy()

_gs_table_years = GS_CONCURRENT | {y + "_gs" for y in GS_STANDALONE}
display["GS election"] = display["Year"].isin(_gs_table_years).map({True: "★", False: ""})

def _year_cell(raw_year: str) -> str:
    label = display_year(raw_year)
    # Link to our own Election page with year as query param
    return f"[{label}](/Election?year={raw_year})"

display["Year"] = display["Year"].map(_year_cell)
display["Candidates"] = display["Candidates"].apply(
    lambda x: str(int(x)) if pd.notna(x) else "—"
)

def _fmt_seats(seats, no_nom):
    s = str(int(seats)) if pd.notna(seats) else "—"
    if pd.notna(no_nom) and int(no_nom) > 0:
        return f"{s} ({int(no_nom)} w/o noms)"
    return s

def _fmt_elected(elected, uncontested):
    e = str(int(elected)) if pd.notna(elected) else "—"
    if pd.notna(uncontested) and int(uncontested) > 0:
        return f"{e} ({int(uncontested)} uncontested)"
    return e

display["Seats"]   = stats.apply(lambda r: _fmt_seats(r.seats, r.no_nom_seats), axis=1)
display["Elected"] = stats.apply(lambda r: _fmt_elected(r.elected, r.uncontested), axis=1)

display["Eligible voters (FE/HE)"] = stats.apply(
    lambda r: _fmt_sector(r.eligible_national, r.eligible_FE, r.eligible_HE, _fmt_int), axis=1)
display["Votes cast (FE/HE)"] = stats.apply(
    lambda r: _fmt_sector(r.cast_national, r.cast_FE, r.cast_HE, _fmt_int), axis=1)
display["Turnout % (FE/HE)"] = stats.apply(
    lambda r: _fmt_sector(r.turnout_national, r.turnout_FE, r.turnout_HE,
                          lambda x: f"{x:.1f}%" if pd.notna(x) else "—"), axis=1)

col_order = ["Year", "GS election", "Seats", "Candidates", "Elected",
             "Eligible voters (FE/HE)", "Votes cast (FE/HE)", "Turnout % (FE/HE)"]
tbl    = display[col_order]
header = "| " + " | ".join(tbl.columns) + " |"
sep    = "| " + " | ".join("---" for _ in tbl.columns) + " |"
rows   = "\n".join(
    "| " + " | ".join(str(v) for v in row) + " |"
    for row in tbl.itertuples(index=False)
)
st.markdown(f"{header}\n{sep}\n{rows}")
