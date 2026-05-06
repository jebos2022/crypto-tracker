import streamlit as st

_CSS = """
<style>
/* ── Typography scale ──────────────────────────────────────────── */
h1 { font-size: 1.5rem !important; font-weight: 600 !important; }
h2 { font-size: 1.125rem !important; font-weight: 600 !important; }
h3 { font-size: 1rem !important; font-weight: 600 !important; }

/* ── Sidebar ────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    border-right: 1px solid #E2E8F0;
    background-color: #F8FAFC !important;
}
[data-testid="stSidebar"] .stTitle {
    font-size: 1rem !important;
    font-weight: 700 !important;
    color: #0F172A;
}
[data-testid="stSidebar"] hr {
    border-color: #E2E8F0;
    margin: 0.5rem 0;
}

/* ── Metric cards ───────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    padding: 0.75rem 1rem !important;
}
[data-testid="stMetricLabel"] {
    font-size: 0.75rem !important;
    font-weight: 500 !important;
    color: #64748B !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
[data-testid="stMetricValue"] {
    font-size: 1.375rem !important;
    font-weight: 700 !important;
    color: #0F172A !important;
}
[data-testid="stMetricDelta"] {
    font-size: 0.75rem !important;
}

/* ── Dataframes ─────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border: 1px solid #E2E8F0;
    border-radius: 6px;
    overflow: hidden;
}

/* ── Borders & containers ───────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: #E2E8F0 !important;
    border-radius: 6px !important;
}

/* ── Buttons ────────────────────────────────────────────────────── */
.stButton > button[kind="primary"] {
    background-color: #2563EB !important;
    border: none !important;
    border-radius: 6px !important;
    font-weight: 500 !important;
    height: 36px !important;
}
.stButton > button[kind="secondary"] {
    border-radius: 6px !important;
    border-color: #E2E8F0 !important;
    font-weight: 500 !important;
    height: 36px !important;
}

/* ── Divider ────────────────────────────────────────────────────── */
hr {
    border-color: #E2E8F0 !important;
    margin: 1rem 0 !important;
}

/* ── Caption / muted text ───────────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
    color: #64748B !important;
    font-size: 0.8125rem !important;
}

/* ── Dashboard nav cards (home page) ───────────────────────────── */
.nav-card {
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 1.25rem 1rem;
    background: #FFFFFF;
    transition: border-color 0.15s, box-shadow 0.15s;
    height: 100%;
}
.nav-card:hover {
    border-color: #2563EB;
    box-shadow: 0 0 0 3px #DBEAFE;
}
.nav-card-icon {
    font-size: 1.5rem;
    margin-bottom: 0.5rem;
    display: block;
}
.nav-card-title {
    font-size: 0.9375rem;
    font-weight: 600;
    color: #0F172A;
    margin-bottom: 0.25rem;
}
.nav-card-desc {
    font-size: 0.8125rem;
    color: #64748B;
    line-height: 1.4;
}
</style>
"""


def apply_design_system() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
