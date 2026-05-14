"""Global Streamlit markup (theme chrome)."""

from __future__ import annotations

from ctis_drift.ui import streamlit_env


def inject_app_theme_styles() -> None:
    """Unobtrusive pharma-style framing; respects Streamlit theme tokens."""
    streamlit_env.st.markdown(
        """
        <style>
        /* Focus visibility for keyboard users */
        button:focus-visible, div[data-baseweb] button:focus-visible {
            outline: 2px solid #0f4f6b;
            outline-offset: 2px;
        }
        .ctis-shell {
            padding: 0.85rem 0 0;
        }
        .ctis-shell h3 {
            font-weight: 650;
            letter-spacing: -0.02em;
            margin-bottom: 0;
        }
        .ctis-kpi {
            border-radius: 10px;
            padding: 0.75rem 0.95rem;
            border: 1px solid rgba(15,79,107,0.22);
            background: linear-gradient(180deg,
                rgba(15,79,107,0.07) 0%,
                rgba(15,79,107,0.02) 100%);
            min-height: 5.75rem;
        }
        div[data-testid="stSidebarNav"] ~ div {
            scrollbar-gutter: stable;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
