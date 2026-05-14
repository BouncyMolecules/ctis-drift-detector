"""Streamlit shell composition."""

from __future__ import annotations

from ctis_drift.config import get_settings
from ctis_drift.constants import APP_ATTRIBUTION
from ctis_drift.ui import streamlit_env
from ctis_drift.ui.bootstrap import bootstrap_runtime
from ctis_drift.ui.pages.api_explorer import tab_api_explorer
from ctis_drift.ui.pages.drift_history import tab_drift_history
from ctis_drift.ui.pages.manage_trials import tab_manage_trials
from ctis_drift.ui.pages.monitored_trials import tab_monitored_trials
from ctis_drift.ui.sidebar import sidebar_shell
from ctis_drift.ui.utils.session import _init_session_defaults
from ctis_drift.ui.utils.theme import inject_app_theme_styles
from ctis_drift.utils.logging import setup_logging


def render_footer() -> None:
    ste = streamlit_env.st
    ste.divider()
    ste.caption(APP_ATTRIBUTION)


def render_app() -> None:
    ste = streamlit_env.st
    settings = get_settings()
    setup_logging(settings.log_level)

    ste.set_page_config(
        layout="wide",
        page_title="CTIS Drift Detector | Vigilance Command Center",
        page_icon=":material/analytics:",
        initial_sidebar_state="expanded",
        menu_items={
            "Get help": None,
            "Report a bug": None,
            "About": (
                "## CTIS Drift Detector\nSubstantive change surveillance for CTIS-derived clinical "
                "trial disclosures."
            ),
        },
    )

    inject_app_theme_styles()
    _init_session_defaults()

    storage, client = bootstrap_runtime(settings)
    sidebar_shell(settings, storage)

    ste.markdown(
        '<main class="ctis-shell" role="main">'
        "<h2>Clinical vigilance cockpit</h2>"
        "<p style='margin-top:0.35rem;color:#4a5b66;margin-bottom:1.35rem'>"
        "Operate a sponsor-grade monitoring desk for CTIS artefacts: cryptographic baselines, "
        "risk-graded deltas, audit exports, and direct API ergonomics.</p>"
        "</main>",
        unsafe_allow_html=True,
    )

    monitored_tab, history_tab, manage_tab, explorer_tab = ste.tabs(
        [
            "1 · Monitored trials",
            "2 · Drift history & details",
            "3 · Add / manage trials",
            "4 · API explorer",
        ],
        key="app_shell_tabs_primary_navigation",
    )

    with monitored_tab:
        tab_monitored_trials(storage, client, settings)
    with history_tab:
        tab_drift_history(storage)
    with manage_tab:
        tab_manage_trials(storage, client)
    with explorer_tab:
        tab_api_explorer(client)

    render_footer()


def main() -> None:
    render_app()
