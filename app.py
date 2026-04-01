"""UCU Elections Explorer — uv run streamlit run app.py"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="UCU Elections",
    page_icon="🗳️",
    layout="wide",
)

DATA_DIR = Path(__file__).parent / "data" / "processed"

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _csv_mtime() -> float:
    return max(p.stat().st_mtime for p in DATA_DIR.glob("*.csv"))


@st.cache_data
def load_data(mtime: float):  # mtime in signature forces cache-bust when CSVs change
    contests   = pd.read_csv(DATA_DIR / "contests.csv")
    candidates = pd.read_csv(DATA_DIR / "candidates.csv")
    ballots    = pd.read_csv(DATA_DIR / "ballots.csv")
    contests["seats"]       = pd.to_numeric(contests["seats"],       errors="coerce")
    contests["valid_votes"] = pd.to_numeric(contests["valid_votes"], errors="coerce")
    ballots["eligible_voters"] = pd.to_numeric(ballots["eligible_voters"], errors="coerce")
    ballots["votes_cast"]      = pd.to_numeric(ballots["votes_cast"],      errors="coerce")
    ballots["turnout_pct"]     = pd.to_numeric(ballots["turnout_pct"],     errors="coerce")
    return contests, candidates, ballots


def year_sort_key(y: str) -> float:
    """Sort '2019-20' after '2019', academic years as mid-year floats.
    Synthetic '_gs' suffix (standalone GS elections) sorts just after the base year."""
    if y.endswith("_gs"):
        return year_sort_key(y[:-3]) + 0.25
    digits = y[:4]
    try:
        base = float(digits)
    except ValueError:
        return 9999.0
    return base + 0.5 if "-" in y or "/" in y else base


def display_year(y: str) -> str:
    """'2019-20' → '2020', '2025-26' → '2026'; '2019_gs' → '2019<br>GS'; single years unchanged."""
    if y.endswith("_gs"):
        return display_year(y[:-3]) + "<br>GS"
    if len(y) > 4 and ("-" in y[4:] or "/" in y[4:]):
        return y[:2] + y[5:]   # "2019-20" → "20" + "20" = "2020"
    return y


contests, candidates, ballots = load_data(mtime=_csv_mtime())

all_years = sorted(contests["year"].unique(), key=year_sort_key)

# GS elections concurrent with national ballot (same electorate, same ballot)
GS_CONCURRENT = {"2012", "2017", "2023-24"}
# GS elections run as standalone ballots (separate from annual national election)
GS_STANDALONE = {"2019"}

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
            elected=("outcome", lambda x: (x == "Elected").sum()),
        )
    )
    .reset_index()
)

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

# Append rows for standalone GS elections (synthetic year key e.g. "2019_gs")
gs_contests   = contests[contests["election_type"] == "general secretary"]
gs_candidates = candidates[candidates["election_type"] == "general secretary"]
for yr in GS_STANDALONE:
    gs_yr_key = yr + "_gs"
    _seats     = gs_contests[gs_contests["year"] == yr]["seats"].sum()
    # Use the contest with the most candidates (count sheet) to avoid ROV duplicates
    _gs_cands_yr = gs_candidates[gs_candidates["year"] == yr]
    _contest_counts = _gs_cands_yr.groupby("contest_id").size()
    if not _contest_counts.empty:
        _main_id  = _contest_counts.idxmax()
        _gs_cands_yr = _gs_cands_yr[_gs_cands_yr["contest_id"] == _main_id]
    _cands   = _gs_cands_yr
    _elected = (_gs_cands_yr["outcome"] == "Elected").sum()
    _ballot = ballots[
        (ballots["election_type"] == "general secretary")
        & (ballots["ballot_type"] == "national")
        & (ballots["year"] == yr)
    ]
    _elig  = _ballot["eligible_voters"].max() if not _ballot.empty else pd.NA
    _cast  = _ballot["votes_cast"].max()      if not _ballot.empty else pd.NA
    _tpct  = _ballot["turnout_pct"].max()     if not _ballot.empty else pd.NA
    gs_row = pd.DataFrame([{
        "year": gs_yr_key,
        "seats": pd.array([int(_seats)], dtype="Int64")[0],
        "candidates": len(_cands),
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

# Standalone GS elections: inject as synthetic year keys (e.g. "2019_gs")
# so they appear as their own x-axis tick on the national line
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

# Build a complete sorted year list so gaps appear in the chart
chart_years = sorted(clean_ballots["year"].unique(), key=year_sort_key)

BALLOT_COLOURS = {
    "national": "#1f77b4",
    "HE":       "#ff7f0e",
    "FE":       "#2ca02c",
}

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

st.title("UCU Elections — Overview")
st.markdown("""
This is an early version of a UCU election data explorer vibe/spec coded by Bijan Parsia using Claude CLI (AI tool). The repository isn't really in a [great state](https://github.com/bparsia/ucuelections) but it's probably usable. 

The scripts scrape the results from various UCU pages as a mix of HTML and (usually but not always) text PDFs. The format is...not entirely regular, so weirdnesses happen.

At the moment, I just share the overall turn out results, which I think are interesting. There may still be errors. Drill downs into each election coming soon.

One personal takeaway is that turnout is low and not obviously correlated with various supposed turn out lowering events I've seen hypothesized (including by me). And we need GTVO in FE even more than in HE.  """)
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

# GS election annotations — concurrent on their own year, standalone on their _gs year
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
    main = fmt(nat)
    parts = "/".join(fmt(v) for v in (fe, he) if pd.notna(v))
    return f"{main} ({parts})" if parts else main

display = stats.rename(columns={"year": "Year", "seats": "Seats",
                                "candidates": "Candidates", "elected": "Elected"}).copy()

_gs_table_years = GS_CONCURRENT | GS_STANDALONE | {y + "_gs" for y in GS_STANDALONE}
display["GS election"] = display["Year"].isin(_gs_table_years).map({True: "★", False: ""})
display["Year"] = display["Year"].map(display_year)
display["Seats"]       = display["Seats"].apply(lambda x: str(int(x)) if pd.notna(x) else "—")
display["Candidates"]  = display["Candidates"].apply(lambda x: str(int(x)) if pd.notna(x) else "—")
display["Elected"]     = display["Elected"].apply(lambda x: str(int(x)) if pd.notna(x) else "—")

display["Eligible voters (FE/HE)"] = stats.apply(
    lambda r: _fmt_sector(r.eligible_national, r.eligible_FE, r.eligible_HE, _fmt_int), axis=1)
display["Votes cast (FE/HE)"] = stats.apply(
    lambda r: _fmt_sector(r.cast_national, r.cast_FE, r.cast_HE, _fmt_int), axis=1)
display["Turnout % (FE/HE)"] = stats.apply(
    lambda r: _fmt_sector(r.turnout_national, r.turnout_FE, r.turnout_HE,
                          lambda x: f"{x:.1f}%" if pd.notna(x) else "—"), axis=1)

col_order = ["Year", "GS election", "Seats", "Candidates", "Elected",
             "Eligible voters (FE/HE)", "Votes cast (FE/HE)", "Turnout % (FE/HE)"]
tbl = display[col_order]
header = "| " + " | ".join(tbl.columns) + " |"
sep    = "| " + " | ".join("---" for _ in tbl.columns) + " |"
rows   = "\n".join("| " + " | ".join(str(v) for v in row) + " |"
                   for row in tbl.itertuples(index=False))
st.markdown(f"{header}\n{sep}\n{rows}")
