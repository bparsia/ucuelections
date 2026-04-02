"""UCU Elections — About."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


import streamlit as st
st.title("About")

st.markdown(Path('pages/writing/about.md').read_text())
