"""UCU Elections Explorer — uv run streamlit run app.py"""

import streamlit as st

st.set_page_config(
    page_title="UCU Elections",
    page_icon="🗳️",
    layout="wide",
)

pg = st.navigation([
    st.Page("pages/0_Overview.py",        title="Elections Overview"),
    st.Page("pages/2_Election.py",        title="Elections"),
    st.Page("pages/1_Candidates.py",      title="Candidate Overview"),
    st.Page("pages/3_Candidate.py",       title="Candidates"),
    st.Page("pages/5_NEC_Overview.py",    title="NEC Overview"),
    st.Page("pages/6_NEC_Year.py",        title="NEC by Year"),
    st.Page("pages/4_About.py",           title="About"),
])
pg.run()
