"""
UCU Elections Explorer — Streamlit app.

Usage:
    uv run streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="UCU Elections Explorer",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = Path(__file__).parent / "data" / "processed"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data
def load_data():
    contests = pd.read_csv(DATA_DIR / "contests.csv")
    candidates = pd.read_csv(DATA_DIR / "candidates.csv")
    rounds = pd.read_csv(DATA_DIR / "stv_rounds.csv")

    # Ensure numeric types
    for col in ["seats", "valid_votes", "invalid_votes"]:
        contests[col] = pd.to_numeric(contests[col], errors="coerce")
    contests["quota"] = contests["quota"].apply(_parse_quota)
    rounds["round"] = pd.to_numeric(rounds["round"], errors="coerce")
    rounds["votes"] = pd.to_numeric(rounds["votes"], errors="coerce")
    rounds["transfer"] = pd.to_numeric(rounds["transfer"], errors="coerce")

    return contests, candidates, rounds


def _parse_quota(val) -> float | None:
    """Parse quota strings like '= 362.34' or '362.34 Votes'."""
    if pd.isna(val):
        return None
    s = str(val).replace(",", "").strip()
    s = s.lstrip("=").strip()
    s = s.split()[0] if s else ""
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------

OUTCOME_COLOURS = {
    "Elected": "#2ca02c",
    "Not Elected": "#d62728",
    "Withdrawn": "#ff7f0e",
    "Uncontested": "#1f77b4",
    "No Nomination": "#9467bd",
}

# ---------------------------------------------------------------------------
# Sidebar — filters
# ---------------------------------------------------------------------------

contests, candidates, rounds = load_data()

st.sidebar.title("🗳️ UCU Elections")

all_years = sorted(contests["year"].unique(), reverse=True)
all_types = sorted(contests["election_type"].unique())

sel_years = st.sidebar.multiselect("Year", all_years, default=all_years)
sel_types = st.sidebar.multiselect("Election type", all_types, default=all_types)
search = st.sidebar.text_input("Search contest name", placeholder="e.g. North West HE")
only_stv = st.sidebar.checkbox("Only contests with STV round data", value=False)

# ---------------------------------------------------------------------------
# Filter contests
# ---------------------------------------------------------------------------

mask = (
    contests["year"].isin(sel_years)
    & contests["election_type"].isin(sel_types)
)
if search:
    mask &= contests["contest_name"].str.contains(search, case=False, na=False)
if only_stv:
    mask &= contests["has_stv_rounds"].astype(str) == "True"

filtered = contests[mask].copy()
filtered = filtered.sort_values(["year", "election_type", "contest_name"], ascending=[False, True, True])

# ---------------------------------------------------------------------------
# Main layout: contest list + detail
# ---------------------------------------------------------------------------

st.sidebar.markdown(f"**{len(filtered)} contest(s)** match")

if filtered.empty:
    st.warning("No contests match the current filters.")
    st.stop()

# Build a display label for the selectbox
filtered["_label"] = filtered.apply(
    lambda r: f"{r['year']} · {r['election_type']} · {r['contest_name']}", axis=1
)

contest_label = st.sidebar.selectbox(
    "Select contest",
    options=filtered["_label"].tolist(),
    index=0,
)

contest_row = filtered[filtered["_label"] == contest_label].iloc[0]
cid = contest_row["contest_id"]

# ---------------------------------------------------------------------------
# Contest detail
# ---------------------------------------------------------------------------

st.title(contest_row["contest_name"])
st.caption(f"{contest_row['year']} · {contest_row['election_type']}")

# Metadata cards
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Seats", int(contest_row["seats"]) if pd.notna(contest_row["seats"]) else "—")
col2.metric("Valid votes", f"{int(contest_row['valid_votes']):,}" if pd.notna(contest_row["valid_votes"]) else "—")
col3.metric("Invalid votes", f"{int(contest_row['invalid_votes']):,}" if pd.notna(contest_row["invalid_votes"]) else "—")
col4.metric("Quota", f"{contest_row['quota']:.2f}" if pd.notna(contest_row["quota"]) else "—")
col5.metric("Rules", contest_row["election_rules"] if pd.notna(contest_row["election_rules"]) else "—")

if pd.notna(contest_row["date"]) and contest_row["date"]:
    st.caption(f"Date: {contest_row['date']}")

st.divider()

# ---------------------------------------------------------------------------
# Candidates for this contest
# ---------------------------------------------------------------------------

cands = candidates[candidates["contest_id"] == cid].copy()
c_rounds = rounds[rounds["contest_id"] == cid].copy()

has_rounds = not c_rounds.empty

# Tabs
if has_rounds:
    tab1, tab2, tab3 = st.tabs(["📊 Vote Progression", "↔️ Transfers", "📋 Results Table"])
else:
    tab1, tab3 = st.tabs(["📋 Results Table", "ℹ️ Source"])
    tab2 = None

# ---------------------------------------------------------------------------
# Tab: Results Table
# ---------------------------------------------------------------------------

with tab3 if not has_rounds else tab3:
    if cands.empty:
        st.info("No candidate data for this contest.")
    else:
        display_cols = ["name", "outcome", "demographic_flags", "first_preferences"]
        display = cands[display_cols].copy()
        display.columns = ["Name", "Outcome", "Flags", "First Preferences"]
        display["First Preferences"] = display["First Preferences"].apply(
            lambda x: f"{x:,.1f}" if pd.notna(x) and x > 0 else ("0" if x == 0 else "—")
        )

        def highlight_outcome(row):
            colour_map = {
                "Elected": "background-color: #d4edda",
                "Not Elected": "",
                "Withdrawn": "background-color: #fff3cd",
                "Uncontested": "background-color: #cce5ff",
            }
            colour = colour_map.get(row["Outcome"], "")
            return [colour] * len(row)

        styled = display.style.apply(highlight_outcome, axis=1)
        st.dataframe(styled, width="stretch", hide_index=True)

        if pd.notna(contest_row["source_pdf"]) and contest_row["source_pdf"]:
            st.caption(f"Source: `{contest_row['source_pdf']}`")

# ---------------------------------------------------------------------------
# Tab: Vote Progression (line chart per candidate)
# ---------------------------------------------------------------------------

if has_rounds:
    with tab1:
        _r = c_rounds[c_rounds["votes"].notna()].copy()

        if _r.empty:
            st.info("No vote data available for this contest.")
        else:
            # Determine outcome per candidate for colour
            outcome_map = dict(zip(cands["name"], cands["outcome"]))
            max_round = int(_r["round"].max())

            fig = go.Figure()

            for name, grp in _r.groupby("name"):
                grp = grp.sort_values("round")
                outcome = outcome_map.get(name, "Not Elected")
                colour = OUTCOME_COLOURS.get(outcome, "#7f7f7f")

                # Add quota line reference
                quota = contest_row["quota"]

                fig.add_trace(go.Scatter(
                    x=grp["round"],
                    y=grp["votes"],
                    mode="lines+markers",
                    name=name,
                    line=dict(
                        color=colour,
                        dash="dot" if outcome == "Withdrawn" else "solid",
                        width=2,
                    ),
                    marker=dict(size=6),
                    hovertemplate=(
                        f"<b>{name}</b><br>"
                        "Round %{x}<br>"
                        "Votes: %{y:,.2f}<extra></extra>"
                    ),
                ))

            # Quota reference line
            if pd.notna(quota) and quota:
                fig.add_hline(
                    y=quota,
                    line_dash="dash",
                    line_color="grey",
                    annotation_text=f"Quota ({quota:,.2f})",
                    annotation_position="right",
                )

            fig.update_layout(
                xaxis_title="Round",
                yaxis_title="Votes",
                xaxis=dict(tickmode="linear", dtick=1),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=500,
                hovermode="x unified",
                margin=dict(r=120),
            )
            st.plotly_chart(fig, width="stretch")

            # Legend explainer
            st.caption(
                "🟢 Elected &nbsp; 🔴 Not Elected &nbsp; 🟠 Withdrawn &nbsp; "
                "— — Quota threshold"
            )

    # ---------------------------------------------------------------------------
    # Tab: Transfers
    # ---------------------------------------------------------------------------

    with tab2:
        transfers = c_rounds[c_rounds["transfer"].notna() & (c_rounds["round"] > 1)].copy()

        if transfers.empty:
            st.info("No transfer data available.")
        else:
            pivot = (
                transfers.pivot_table(
                    index="name", columns="round", values="transfer", aggfunc="first"
                )
                .fillna(0)
            )

            # Sort by outcome then name
            outcome_order = {"Elected": 0, "Not Elected": 2, "Withdrawn": 1}
            pivot["_order"] = pivot.index.map(
                lambda n: outcome_order.get(outcome_map.get(n, "Not Elected"), 3)
            )
            pivot = pivot.sort_values("_order").drop(columns="_order")

            col_labels = {c: f"Stage {c}" for c in pivot.columns}
            pivot.columns = [col_labels.get(c, c) for c in pivot.columns]

            # Heatmap of transfers
            fig2 = go.Figure(go.Heatmap(
                z=pivot.values,
                x=list(pivot.columns),
                y=list(pivot.index),
                colorscale=[
                    [0.0, "#d62728"],   # losses = red
                    [0.5, "#ffffff"],   # zero = white
                    [1.0, "#2ca02c"],   # gains = green
                ],
                zmid=0,
                text=[[f"{v:+.1f}" if v != 0 else "" for v in row] for row in pivot.values],
                texttemplate="%{text}",
                hovertemplate="<b>%{y}</b><br>%{x}: %{z:+.2f}<extra></extra>",
                showscale=True,
                colorbar=dict(title="Transfer"),
            ))
            fig2.update_layout(
                xaxis_title="Round",
                yaxis_title="Candidate",
                height=max(300, 40 * len(pivot) + 100),
                margin=dict(l=200),
            )
            st.plotly_chart(fig2, width="stretch")
            st.caption(
                "Green = votes received, Red = votes lost (election surplus transferred or elimination). "
                "Rounds shown are stages 2+ only."
            )

# ---------------------------------------------------------------------------
# Source info for non-STV tab
# ---------------------------------------------------------------------------

if not has_rounds and tab2 is None:
    with tab1:
        # tab1 is actually the results table for non-STV contests
        pass
    with tab3:
        if pd.notna(contest_row["source_pdf"]) and contest_row["source_pdf"]:
            st.caption(f"Source: `{contest_row['source_pdf']}`")
        st.info(
            "No round-by-round STV data available for this contest. "
            "It may be from a ROV summary PDF (elected names only), "
            "an uncontested result, or a scanned image PDF."
        )

# ---------------------------------------------------------------------------
# Footer stats in sidebar
# ---------------------------------------------------------------------------

st.sidebar.divider()
st.sidebar.markdown(
    f"**Dataset:** {len(contests)} contests · {len(candidates)} candidates  \n"
    f"**Years:** {min(all_years)} – {max(all_years)}  \n"
    f"**STV rounds:** {len(rounds):,} rows"
)
