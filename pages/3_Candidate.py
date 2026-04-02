"""UCU Elections — individual candidate profile page."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from utils import _csv_mtime, display_year, load_data, year_sort_key

contests, candidates, ballots = load_data(mtime=_csv_mtime())

# ---------------------------------------------------------------------------
# Load STV rounds for final-vote lookup
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.parent / "data" / "processed"

@st.cache_data
def load_rounds(mtime: float) -> pd.DataFrame:
    return pd.read_csv(DATA_DIR / "stv_rounds.csv", dtype={"year": str})

rounds = load_rounds(mtime=_csv_mtime())

# ---------------------------------------------------------------------------
# Candidate list and selection
# ---------------------------------------------------------------------------

uk = candidates[candidates["election_type"] == "UK national"].copy()
name_col = "name_canonical" if "name_canonical" in uk.columns else "name"

all_names = sorted(uk[name_col].dropna().unique(), key=str.casefold)

qp_name = st.query_params.get("candidate", all_names[0] if all_names else "")
if qp_name not in all_names:
    qp_name = all_names[0] if all_names else ""

selected_name = st.selectbox(
    "Candidate",
    all_names,
    index=all_names.index(qp_name) if qp_name in all_names else 0,
)
if selected_name != qp_name:
    st.query_params["candidate"] = selected_name
    st.rerun()

# ---------------------------------------------------------------------------
# Filter to this candidate's appearances
# ---------------------------------------------------------------------------

cand_rows = uk[uk[name_col] == selected_name].copy()
cand_rows = cand_rows.sort_values("election_id", key=lambda s: s.map(year_sort_key))

# ---------------------------------------------------------------------------
# Final-vote lookup from STV rounds (max round, votes column)
# ---------------------------------------------------------------------------

def final_votes(contest_id: str, raw_name: str) -> float | None:
    """Return the last-round vote tally for this candidate in this contest."""
    mask = (rounds["contest_id"] == contest_id) & (rounds["name"] == raw_name)
    sub = rounds[mask]
    if sub.empty:
        return None
    last = sub.loc[sub["round"].astype(int).idxmax()]
    v = last["votes"]
    return float(v) if pd.notna(v) else None


# ---------------------------------------------------------------------------
# Header and summary metrics
# ---------------------------------------------------------------------------

st.title(selected_name)

n_elections = cand_rows["election_id"].nunique()
n_wins      = cand_rows["outcome"].isin({"Elected", "Uncontested"}).sum()
win_rate    = f"{int(n_wins / n_elections * 100)}%" if n_elections else "—"

m1, m2, m3 = st.columns(3)
m1.metric("Elections entered", n_elections)
m2.metric("Wins", n_wins)
m3.metric("Win rate", win_rate)

# ---------------------------------------------------------------------------
# Appearances table
# ---------------------------------------------------------------------------

st.subheader("Election history")

rows_out = []
for _, row in cand_rows.iterrows():
    fp  = row["first_preferences"]
    fv  = final_votes(row["contest_id"], row["name"])
    rows_out.append({
        "Year":        f"[{display_year(row['election_id'])}](/Election?year={row['year']})",
        "Contest":     row["contest_name"],
        "1st prefs":   f"{int(fp):,}" if pd.notna(fp) and fp else "—",
        "Final votes": f"{int(fv):,}" if fv and fv != fp else "—",
        "Outcome":     f"**{row['outcome']}**" if row["outcome"] in {"Elected", "Uncontested"}
                       else row["outcome"],
    })

tbl    = pd.DataFrame(rows_out)
header = "| " + " | ".join(tbl.columns) + " |"
sep    = "| " + " | ".join("---" for _ in tbl.columns) + " |"
rows_md = "\n".join(
    "| " + " | ".join(str(v) for v in r) + " |"
    for r in tbl.itertuples(index=False)
)
st.markdown(f"{header}\n{sep}\n{rows_md}")
