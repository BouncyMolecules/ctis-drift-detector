"""Global Streamlit markup: enterprise visual system and onboarding chrome.

Design intent
-------------
* Trust-forward palette suitable for regulatory / clinical operations contexts.
* Streamlit-native light and dark themes: we layer brand accents on top of
  Streamlit's theme tokens so contrast and accessibility remain tied to the
  viewer's chosen appearance (Settings → Theme).
* All styling is injected once per run via ``st.markdown(..., unsafe_allow_html=True)``.

See: ``inject_app_theme_styles`` and ``render_onboarding_banner``.
"""

from __future__ import annotations

from ctis_drift.ui import streamlit_env
from ctis_drift.ui.utils.session import (
    _SS_ONBOARDING_DISMISSED,
    _SS_ONBOARDING_PORTFOLIO_WELCOME_DONE,
)

# ── Brand tokens (reference in comments / future asset pipelines) ───────────
_CTIS_NAVY_DEEP = "#0A1428"
_CTIS_TEAL_ACCENT = "#00D4FF"


def inject_app_theme_styles() -> None:
    """Inject scoped CSS for typography, layout chrome, and Streamlit widgets.

    Uses Streamlit CSS variables (``--text-color``, ``--background-color``, …)
    so the same rules behave correctly in both light and dark application
    themes without duplicating entire stylesheets.
    """
    streamlit_env.st.markdown(
        f"""
        <style>
        /* ------------------------------------------------------------------
           CTIS Drift Detector — clinical vigilance UI shell
           Primary: navy {_CTIS_NAVY_DEEP} · Accent: teal {_CTIS_TEAL_ACCENT}
           ------------------------------------------------------------------ */

        /* Brand tokens extend Streamlit theme variables (set on this node in Streamlit ≥1.16). */
        .stApp {{
            --ctis-navy-deep: {_CTIS_NAVY_DEEP};
            --ctis-teal: {_CTIS_TEAL_ACCENT};
            --ctis-teal-soft: color-mix(in srgb, var(--ctis-teal) 22%, transparent);
            --ctis-navy-ink: color-mix(in srgb, var(--ctis-navy-deep) 78%, var(--text-color) 22%);
            --ctis-card-edge: color-mix(in srgb, var(--text-color) 14%, transparent);
            --ctis-card-tint: color-mix(in srgb, var(--ctis-teal) 12%, var(--background-color));
            --ctis-radius-lg: 14px;
            --ctis-radius-md: 10px;
            --ctis-shadow-elev: 0 8px 28px rgba(10, 20, 40, 0.14);
            /* System stack avoids external font requests (common constraint in locked-down QA). */
            --ctis-font-display: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue",
                Arial, sans-serif;
            --ctis-font-mono: "Cascadia Code", "Consolas", "JetBrains Mono", monospace;
            font-family: var(--ctis-font-display);
            letter-spacing: -0.01em;
        }}

        /* Main canvas breathing room */
        section.main > div {{
            max-width: 1440px;
            padding-top: 1.1rem;
            padding-bottom: 2.5rem;
        }}

        /* Headings inherit theme text colour; tighten for “report” feel */
        .ctis-shell h2, .ctis-shell h3 {{
            font-weight: 650;
            letter-spacing: -0.025em;
            color: var(--text-color);
            margin-bottom: 0.35rem;
        }}

        .ctis-hero-subtitle {{
            margin-top: 0.35rem;
            margin-bottom: 1.35rem;
            color: color-mix(in srgb, var(--text-color) 72%, transparent);
            font-size: 1.02rem;
            line-height: 1.55;
            max-width: 58rem;
        }}

        /* Metric / KPI tiles */
        .ctis-kpi {{
            border-radius: var(--ctis-radius-md);
            padding: 0.85rem 1rem;
            min-height: 5.75rem;
            border: 1px solid var(--ctis-card-edge);
            background: linear-gradient(
                165deg,
                var(--ctis-card-tint) 0%,
                color-mix(in srgb, var(--secondary-background-color) 88%, transparent) 100%
            );
            box-shadow: 0 1px 0 color-mix(in srgb, var(--text-color) 6%, transparent);
        }}

        [data-testid="stMetricValue"] {{
            color: var(--ctis-navy-ink);
            font-weight: 680;
        }}

        [data-testid="stMetricLabel"] {{
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.72rem;
            letter-spacing: 0.06em;
            color: color-mix(in srgb, var(--text-color) 58%, transparent);
        }}

        /* Data containers & tables */
        div[data-testid="stDataFrame"] {{
            border-radius: var(--ctis-radius-lg);
            border: 1px solid var(--ctis-card-edge);
            overflow: hidden;
            box-shadow: var(--ctis-shadow-elev);
        }}

        [data-testid="stHorizontalBlock"] div[data-testid="stColumn"] {{
            min-width: 0;
        }}

        /* Tabs — calmer, instrument-like */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 0.35rem;
            border-bottom: 1px solid var(--ctis-card-edge);
            padding-bottom: 2px;
        }}

        .stTabs [data-baseweb="tab"] {{
            border-radius: var(--ctis-radius-md) var(--ctis-radius-md) 0 0;
            padding: 0.55rem 0.95rem;
            font-weight: 600;
            letter-spacing: 0.01em;
        }}

        .stTabs [aria-selected="true"] {{
            color: var(--ctis-navy-ink);
            border-bottom: 2px solid var(--ctis-teal) !important;
        }}

        /* Buttons — primary emphasis uses teal accent */
        .stButton > button {{
            border-radius: var(--ctis-radius-md);
            font-weight: 650;
            letter-spacing: 0.02em;
            border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
            transition: background-color 120ms ease, box-shadow 120ms ease, transform 80ms ease;
        }}

        .stButton > button:focus-visible {{
            outline: 2px solid var(--ctis-teal);
            outline-offset: 2px;
        }}

        /* Download / secondary actions */
        .stDownloadButton > button {{
            border-radius: var(--ctis-radius-md);
            font-weight: 600;
        }}

        /* Sidebar */
        section[data-testid="stSidebar"] {{
            border-right: 1px solid var(--ctis-card-edge);
            background: linear-gradient(
                180deg,
                color-mix(in srgb, var(--secondary-background-color) 96%, var(--ctis-teal) 4%) 0%,
                var(--secondary-background-color) 100%
            );
        }}

        section[data-testid="stSidebar"] .stMarkdown p,
        section[data-testid="stSidebar"] span {{
            color: color-mix(in srgb, var(--text-color) 92%, transparent);
        }}

        /* Alerts & callouts */
        div[data-testid="stAlert"] {{
            border-radius: var(--ctis-radius-md);
            border: 1px solid var(--ctis-card-edge);
        }}

        /* Selects, inputs */
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] input {{
            border-radius: var(--ctis-radius-md) !important;
        }}

        /* Dividers */
        hr {{
            border: none;
            border-top: 1px solid var(--ctis-card-edge);
            margin: 1.5rem 0;
        }}

        .ctis-muted-page-lede {{
            margin-top: 0.35rem;
            margin-bottom: 0.85rem;
            color: color-mix(in srgb, var(--text-color) 70%, transparent);
            line-height: 1.5;
        }}

        /* Onboarding banner */
        .ctis-onboarding {{
            border-radius: var(--ctis-radius-lg);
            border: 1px solid color-mix(in srgb, var(--ctis-teal) 45%, var(--ctis-card-edge));
            background: linear-gradient(
                120deg,
                color-mix(in srgb, var(--ctis-teal) 14%, var(--secondary-background-color)) 0%,
                color-mix(in srgb, var(--ctis-navy-deep) 16%, var(--secondary-background-color)) 100%
            );
            box-shadow: var(--ctis-shadow-elev);
            padding: 1.15rem 1.35rem;
            position: relative;
            overflow: hidden;
            margin-bottom: 1.15rem;
        }}

        .ctis-onboarding::before {{
            content: "";
            position: absolute;
            inset: 0;
            background: radial-gradient(
                800px 120px at 0% 0%,
                var(--ctis-teal-soft),
                transparent 58%
            );
            pointer-events: none;
        }}

        .ctis-onboarding-inner {{
            position: relative;
            z-index: 1;
        }}

        .ctis-onboarding-title {{
            margin: 0 0 0.45rem 0;
            font-size: 1.08rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: var(--text-color);
        }}

        .ctis-onboarding-body {{
            margin: 0;
            color: color-mix(in srgb, var(--text-color) 82%, transparent);
            font-size: 0.98rem;
            line-height: 1.58;
        }}

        .ctis-onboarding-steps {{
            margin: 0.75rem 0 0 0;
            padding-left: 1.15rem;
            color: color-mix(in srgb, var(--text-color) 78%, transparent);
            line-height: 1.55;
            font-size: 0.94rem;
        }}

        /* Scrollbar stabilisation */
        div[data-testid="stSidebarNav"] ~ div {{
            scrollbar-gutter: stable;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_onboarding_banner(*, trial_count: int) -> None:
    """Render welcome / orientation panel when appropriate; handles dismiss.

    Visibility
    * **Empty portfolio**: keep visible on every rerun until the user dismisses.
    * **Trials on file**: show once per browser session (first successful paint),
      unless dismissed earlier — mirrors a concise “first load” briefing without
      nagging experienced operators.

    Dismissal is stored in :class:`streamlit.runtime.state.SessionState` only
    (session lifetime); it resets when the session restarts.
    """
    ste = streamlit_env.st
    dismissed = bool(ste.session_state.get(_SS_ONBOARDING_DISMISSED, False))
    portfolio_intro_done = bool(
        ste.session_state.get(_SS_ONBOARDING_PORTFOLIO_WELCOME_DONE, False)
    )

    if dismissed:
        return
    if trial_count > 0 and portfolio_intro_done:
        return

    left, right = ste.columns([5.15, 1], gap="medium")
    with left:
        ste.markdown(
            """
            <div class="ctis-onboarding">
              <div class="ctis-onboarding-inner">
                <p class="ctis-onboarding-title">Welcome to the vigilance desk</p>
                <p class="ctis-onboarding-body">
                  <strong>CTIS Drift Detector</strong> supports substantive change surveillance for
                  EU Clinical Trials Information System (CTIS) trial disclosures.
                  It anchors cryptographic baselines, compares successive public snapshots, and
                  surfaces risk-graded drift for your monitored portfolio when disclosures evolve.
                </p>
                <ol class="ctis-onboarding-steps">
                  <li><strong>Enrol trials</strong> under <em>Add / manage trials</em> (EU CT number or JSON snapshot).</li>
                  <li><strong>Run evaluations</strong> from <em>Monitored trials</em> to capture drift scores and history.</li>
                  <li><strong>Review and export</strong> drift records and audit bundles for governance workflows.</li>
                </ol>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        ste.markdown("<div style='height:0.5rem'></div>", unsafe_allow_html=True)
        if ste.button(
            "Dismiss",
            key="ctis_onboarding_dismiss",
            use_container_width=True,
            help="Hide this briefing for the current session. You can clear session state to see it again.",
        ):
            ste.session_state[_SS_ONBOARDING_DISMISSED] = True
            ste.session_state[_SS_ONBOARDING_PORTFOLIO_WELCOME_DONE] = True
            ste.rerun()

    # After first display with a populated register, suppress repeat briefings.
    if trial_count > 0:
        ste.session_state[_SS_ONBOARDING_PORTFOLIO_WELCOME_DONE] = True
