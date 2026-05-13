"""Launch the Streamlit app: `python -m ctis_drift` or the `ctis-drift-app` console script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Run Streamlit against `main.py` in this package."""
    app = Path(__file__).resolve().parent / "main.py"
    raise SystemExit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)]))


if __name__ == "__main__":
    main()
