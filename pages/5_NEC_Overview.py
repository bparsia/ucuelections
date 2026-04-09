"""UCU Elections — NEC stability overview page."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import _csv_mtime

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data" / "processed"


@st.cache_data
def load_stability(mtime: float) -> pd.DataFrame:
    path = DATA_DIR / "nec_stability.csv"
    df = pd.read_csv(path, dtype={"year": str})
    return df


stability = load_stability(mtime=_csv_mtime())

# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------

st.title("NEC Stability")

if stability.empty:
    st.warning("No NEC stability data found. Run `normalise.py` to generate it.")
    st.stop()

# Year as categorical label (not numeric axis)
years = stability["year"].tolist()

col_left, col_right = st.columns(2)

# --- Left chart: NEC size over time ---
with col_left:
    fig_size = go.Figure()
    fig_size.add_trace(go.Scatter(
        x=years,
        y=stability["total_members"].tolist(),
        mode="lines+markers",
        name="Total members",
        line=dict(color="steelblue", width=2),
        marker=dict(size=6),
    ))
    fig_size.update_layout(
        title="NEC size over time",
        xaxis_title="Year",
        yaxis_title="Members",
        xaxis=dict(type="category"),
        margin=dict(l=40, r=20, t=50, b=40),
        height=350,
    )
    st.plotly_chart(fig_size, use_container_width=True)

# --- Right chart: % new members ---
with col_right:
    fig_new = go.Figure()
    fig_new.add_trace(go.Scatter(
        x=years,
        y=stability["pct_new_vs_prev"].tolist(),
        mode="lines+markers",
        name="% new vs prev year",
        line=dict(color="darkorange", width=2),
        marker=dict(size=6),
    ))
    fig_new.add_trace(go.Scatter(
        x=years,
        y=stability["pct_new_ever"].tolist(),
        mode="lines+markers",
        name="% brand new ever",
        line=dict(color="crimson", width=2, dash="dot"),
        marker=dict(size=6),
    ))
    fig_new.update_layout(
        title="% new members",
        xaxis_title="Year",
        yaxis_title="% of committee",
        xaxis=dict(type="category"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=40, r=20, t=70, b=40),
        height=350,
    )
    st.plotly_chart(fig_new, use_container_width=True)

# --- Summary table ---
st.subheader("Year-by-year stability")
display_df = stability.rename(columns={
    "year":           "Year",
    "total_members":  "Members",
    "new_ever":       "New ever",
    "new_vs_prev":    "New vs prev",
    "pct_new_ever":   "% new ever",
    "pct_new_vs_prev": "% new vs prev",
})
st.dataframe(display_df, hide_index=True, use_container_width=True)
