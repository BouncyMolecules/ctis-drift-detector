"""Session helpers and widgets keys shared across tabs."""

from __future__ import annotations

from typing import Any, Final

from ctis_drift.ui import streamlit_env

_SS_ACTION_TRIAL: Final[str] = "_ctis_action_trial_euct"
_SS_REFRESH_TOKEN: Final[str] = "_ctis_data_refresh"
# Onboarding banner (session-scoped; cleared when Streamlit starts a new session)
_SS_ONBOARDING_DISMISSED: Final[str] = "_ctis_onboarding_dismissed"
_SS_ONBOARDING_PORTFOLIO_WELCOME_DONE: Final[str] = "_ctis_onboarding_portfolio_welcome_done"


def _init_session_defaults() -> None:
    defaults: dict[str, Any] = {
        _SS_ACTION_TRIAL: "",
        _SS_REFRESH_TOKEN: 0,
        _SS_ONBOARDING_DISMISSED: False,
        _SS_ONBOARDING_PORTFOLIO_WELCOME_DONE: False,
    }
    for key, value in defaults.items():
        if key not in streamlit_env.st.session_state:
            streamlit_env.st.session_state[key] = value


def _bump_data_refresh() -> None:
    session_state = streamlit_env.st.session_state
    session_state[_SS_REFRESH_TOKEN] = int(session_state.get(_SS_REFRESH_TOKEN, 0)) + 1
