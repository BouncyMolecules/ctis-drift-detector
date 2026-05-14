"""
CTIS Drift Sentinel — hosted entry point for Streamlit Community Cloud.

Keeps bootstrap minimal: prepend ``src/`` when the editable install layout is not
present, then delegate to ``ctis_drift.main`` (canonical page config and UX).
"""

from __future__ import annotations

import logging
import sys
from contextlib import suppress
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if _SRC.is_dir():
    src_str = str(_SRC)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


def main() -> None:
    """Run the Streamlit application (invoked via ``streamlit run app.py``)."""
    import streamlit as st
    from streamlit.errors import StreamlitAPIException

    try:
        from ctis_drift.main import main as run_application
    except ImportError:
        logging.basicConfig(level=logging.INFO)
        log = logging.getLogger(__name__)
        log.exception(
            "Failed to import ctis_drift; verify package layout "
            "(src/ctis_drift) and installed dependencies."
        )
        with suppress(StreamlitAPIException):
            st.set_page_config(
                layout="wide",
                page_title="CTIS Drift Sentinel | Startup",
                page_icon=":material/error:",
                initial_sidebar_state="collapsed",
                menu_items={"Get help": None, "Report a bug": None, "About": None},
            )
        st.title("Application failed to initialise")
        st.error(
            "The CTIS Drift Sentinel package could not be loaded. For Streamlit Cloud, confirm "
            "the repository contains `src/ctis_drift`, **Main file path** is `app.py`, and your "
            "dependencies file resolves (for example `requirements.txt`)."
        )
        st.caption(
            "Administrators should inspect stderr or container logs where this process runs; "
            "set CTIS_DRIFT_LOG_LEVEL=DEBUG locally for finer-grained diagnostics."
        )
        st.stop()

    run_application()


if __name__ == "__main__":
    main()
