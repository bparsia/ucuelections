"""UCU Elections Explorer — uv run streamlit run app.py"""

import streamlit as st

st.set_page_config(
    page_title="UCU Elections",
    page_icon="🗳️",
    layout="wide",
)

pg = st.navigation([
    st.Page("pages/0_Overview.py",   title="Overview",   icon="🗳️"),
    st.Page("pages/1_Candidates.py", title="Candidates", icon="👤"),
    st.Page("pages/2_Election.py",   title="Election",   icon="📋"),
    st.Page("pages/3_Candidate.py",  title="Candidate",  icon="🧑"),
])
pg.run()
