<div align="center">

# CTIS Drift Sentinel

### Substantive-change surveillance for EU CTIS public artefacts—built for sponsors, CROs, and vigilance teams who cannot afford silent drift.

[**Try live demo**](https://ctis-drift-detector.streamlit.app) · [Quick start](#quick-start) · [Deploy](#deploy-streamlit-community-cloud) · [GxP posture](#gxp-regulatory-compliance)

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://ctis-drift-detector.streamlit.app)

*Clinical operations intelligence that reads like a cockpit, explains itself like an audit memo, and exports like something you could walk into RAS with.*

</div>

---

## Why this matters

The EU Clinical Trials Information System (CTIS) is consolidating trial status, documentation, timelines, authority engagement, and public disclosure—but **those records move**. Sponsors face a blunt reality: regulators, sites, monitors, PV, labeling, submissions, partner organisations (and timelines) react to deltas they did not see coming. Operational teams must translate “something changed somewhere in JSON” into **traceable governance**: what changed, when, how material it was, and what to do next.

**CTIS Drift Sentinel** is an operations-ready command centre over **cryptographically anchored snapshots** and a **risk-graded drift engine**. It turns raw CTIS payloads into dashboards, timelines, forensic JSON, and workbook exports aligned with how Regulatory Operations leaders actually decide—without claiming to replace your validated systems of record.

---

## What you get (features → outcomes)

- **Portfolio monitoring desk** — One view across enrolled EU CT identifiers: last polls, fingerprints, drift bands, and headline counts for elevated critical risk—what managers need in stand-ups.
- **Regulatory-risk scoring** — Deterministic ontology (status transitions, milestones, RFIs/queries, document corpus churn, regulator engagement hints, PV signals, sponsor/site deltas) rolled into reproducible LOW → CRITICAL posture with explicit rule contributions—not an opaque score.
- **Immutable snapshot lineage** — Canonical JSON hashing and snapshot persistence so inspections can answer “prove what you knew, when” instead of debating screenshots.
- **Drift history with evidence** — Per-run summaries, sampled changed paths, downloadable JSON artefacts, and charts for evaluation cadence and trial-level risk trajectory.
- **One-click ingestion and probes** — Fetch CTIS payloads, optionally evaluate drift before anchoring baseline, duplicate-hash deduplication toggle, sandbox JSON paste pathway for demos and migrations.
- **API ergonomics for integrators** — Typed search/retrieve envelopes and health probing for teams negotiating CTIS quirks (timeouts, pagination, payloads) without living in Postman alone.
- **Audit bundle exports** — Excel workbook (monitoring register, drift-run archive, lightweight document-control sheet) and PDF appendix suited to an internal submission memo when refreshed ahead of milestones.

---

## Screenshots

*Add PNG or WebP files under `docs/screenshots/` using the filenames below so links stay stable on LinkedIn and GitHub previews.*

### 1 · Monitored portfolio — KPI strip and risk-banded registry

![CTIS Drift Sentinel monitored trials dashboard showing KPI metrics, EU CT identifiers, colour-coded risk bands, content fingerprints, and last poll timestamps in a Streamlit-wide layout.](docs/screenshots/monitored-portfolio.png)

*Caption: Operational triage—who moved, how severe the latest evaluation is, and which trial to action next.*

### 2 · Drift history — forensic lineage and downloadable JSON artefacts

![Drift history and forensic detail panel with UTC timestamps, expandable per-run narratives showing human-readable summaries, sampled changed-field JSON, structural summaries, and a download button for full drift report JSON.](docs/screenshots/drift-history.png)

*Caption: From “something changed” to inspectable structured evidence suitable for escalation packets.*

### 3 · Add / manage trials — ingestion, baseline discipline, sandbox JSON

![Add and manage trials workspace with CTIS retrieve flow, drift evaluation toggle, duplicate-hash suppression option, keyed JSON preview, and manual onboarding text area for sandbox or migration payloads.](docs/screenshots/manage-trials.png)

*Caption: Enrol trials with ingestion controls that mirror cautious sponsor practice—not reckless scraping.*

---

<a id="try-live-demo"></a>

## Try live demo

Hosted on **Streamlit Community Cloud**. Open the production-grade cockpit directly — no local install required for evaluation walkthroughs.

| | |
| :--- | :--- |
| **Hosted app** | **[https://ctis-drift-detector.streamlit.app](https://ctis-drift-detector.streamlit.app)** |
| **Entry point** | Root-level `app.py` (delegates to `ctis_drift.main`) |

**Responsible use.** The deployment is suited to demonstrations, stakeholder reviews, and engineering interviews unless you overlay your organisation’s **CSV/IQ-OQ-equivalent**, secret management in the Cloud dashboard, retention policy, and validation evidence packages. Prefer **least-privilege** API access and assume Community Cloud ephemeral storage resets with platform lifecycle unless you deliberately externalise SQLite or wire a governed database backend.

Should your assigned Streamlit subdomain differ after first deploy (for example rebranding under a different slug), substitute that hostname in inbound links — the README uses `ctis-drift-detector` as the canonical demonstration URL.

<a id="deploy-streamlit-community-cloud"></a>

## Deploy on Streamlit Community Cloud

Minimal, reproducible posture for Regulatory Operations–adjacent tooling: everything versioned Git-side; nothing sensitive baked into artefacts.

### Prerequisite layout (this repository)

| Path | Purpose |
| :--- | :--- |
| **`app.py`** | Cloud entry — prepends `src/` to `PYTHONPATH`, imports `ctis_drift.main` |
| **`requirements.txt`** | Pinned dependency surface consumed by Streamlit installers |
| **`.streamlit/config.toml`** | Theme, telemetry opt-out, ergonomic defaults (**no secrets**) |
| **`src/ctis_drift/`** | Application package |

### Steps

1. **Push this repository** to GitHub — verify `app.py`, `requirements.txt`, and `.streamlit/config.toml` are tracked.
2. Sign in at **[share.streamlit.io](https://share.streamlit.io)** and choose **Deploy a public/private app**.
3. **Repository & branch**: select your fork and deployment branch (typically `main`).
4. **Main file path**: `app.py`.
5. **Requirements file**: `requirements.txt` (pinned in-repo; aligns with **`pyproject.toml`** intent).
6. **Python version**: set **Advanced settings** → **Python 3.11** when offered (matches `requires-python`).
7. **Secrets (mandatory before production CTIS egress)** — in the Streamlit dashboard, open **⚙ Secrets** and supply at least what your environment dictates, for example:
   ```
   CTIS_API_BASE_URL = "…"
   CTIS_API_TOKEN = "…"   # if your tenant requires bearer auth
   CTIS_DRIFT_DATABASE_URL = "sqlite:///mount/ctis_drift.db"   # or your governed URI
   ```
   Never commit a local `.streamlit/secrets.toml` — keep secrets in Cloud or your enterprise secret manager mirrored there.
8. **Deploy**. After build success, optionally wire a **custom domain** or rename the subdomain in Streamlit Settings to match **`https://ctis-drift-detector.streamlit.app`** (adjust README links accordingly if yours differs).

**Persistence note.** Default `CTIS_DRIFT_DATABASE_URL` is `sqlite:///data/ctis_drift.db` (relative URI). Ensure the filesystem path referenced by SQLite is writable in your host tier; provision a stable volume attachment or remote database if Regulatory Operations requires durable audit logs across container restarts.

---

## Quick start

**Prerequisites:** Python **3.11+** (3.11–3.13 recommended on Windows until scientific wheels stabilise on newer interpreters), `pip`, and network egress to your configured CTIS public API host.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -e .
```

Copy `.env.example` → `.env` and set database path, API base URL (and token if applicable), timeouts, logging, and optional mock toggles—see `src/ctis_drift/config.py` for authoritative settings.

Ensure `data/` is writable (tracked with `.gitkeep`).

Run the cockpit (matches Streamlit Cloud — root entry):

```bash
streamlit run app.py
```

Direct package path (maintainers debugging UI without the bootstrap shim):

```bash
streamlit run src/ctis_drift/main.py
```

Equivalent entrypoint after editable install:

```bash
ctis-drift-app
```

**Quality bar (optional, maintainers)**

```bash
pip install -e ".[dev]"
ruff check src
mypy src/ctis_drift
pytest
```

---

## How it works

**For executives and directors.** The application answers four governance questions: *did the public trial record diverge*, *was that divergence material*, *can we show what we understood and when*, and *can we package that narrative for escalation or filings*. It combines polling/ingestion UX, cryptographic anchoring for JSON snapshots, deterministic scoring narratives, SQLite persistence suited to workstation-scale audit logs, and export paths that mirror how Regulatory Ops already assembles dossier hygiene packets.

**For engineering and quality leads.**

1. **Transport layer** (`ctis_api`) calls CTIS-compatible JSON endpoints via `httpx` / `requests` with typed payloads (search, retrieve, health).
2. **Persistence layer** (`storage`) persists trial registry rows, hashed snapshots (`compute_json_sha256` canonical encoding), and drift run lineage through SQLModel / SQLite (`StorageService`).
3. **Domain engine** (`drift_detector`) walks structured JSON diffs, classifies pathway signals into regulated categories, merges structural churn cost and categorical weights, emits `DriftReport` objects with audited rule contributions (`RuleContribution`), and maps risk mass into enumerated bands (`RiskLevel`).
4. **Experience layer** (`main`) stitches Streamlit layout, Plotly visuals, KPI semantics, workbook/PDF exporters, sandbox numeric drift for UI rehearsal, defensive API error narration, sidebar environment transparency, and session-state ergonomics.

The architecture separates regulatory scoring from persistence and Streamlit concerns—the engine is testable without a GUI and can run in batch if your SDLC prefers containerised jobs.

---

<a id="gxp-regulatory-compliance"></a>

## GxP / regulatory compliance posture

This repository is a **professional portfolio build** illustrating how operational vigilance tooling can embody ALCOA-friendly principles **by design**. It does **not** ship as a commercially validated computerised system replacement for regulated production **as-is**.

| Concern | How the design maps |
| :--- | :--- |
| **Traceability & contemporaneous records** | UTC timestamps throughout persistence; expandable drift artefacts; exports aligned with traceability workbook expectations. |
| **Data integrity signalling** | Content fingerprints (SHA‑256 via canonical JSON) gate whether deep diff logic runs; hashed snapshots underpin cryptographic drift narratives. |
| **Human accountability** | Human-readable summaries, explicit risk ladders, enumerated rule rationales—not an opaque classifier. |
| **Segregation of duties & environment control** | Settings via environment / `.env` (not baked into binaries); sidebar surfaces a read-only environment snapshot for reproducible incident review. |

**Responsible deployment.** Map this pattern into your organisational **CSV / risk assessment**, IQ/OQ-equivalent harnesses, authorised SOP overlays, retention policies, privileged access pathways, immutable log shipping, anomaly detection across API availability, controlled vocabulary alignment for category weights, periodic governance of scoring thresholds, formal change control for ontology updates, and **validation evidence** suited to Annex 11 / CSA expectations before production clinical use.

---

## Technology stack

| Layer | Choices |
| :--- | :--- |
| **Experience** | Streamlit (`main.py`), Plotly visuals, pharma-oriented bespoke CSS |
| **Language & typing** | Python 3.11+, Pydantic v2 typed models (`drift_detector`, API envelopes) |
| **Persistence** | SQLite via SQLModel (audit-friendly local deployment default) |
| **Integrations** | HTTP client stack (`httpx`, `requests`) with defensive error taxonomy |
| **Exports** | `openpyxl` (Excel workbook), `fpdf2` (PDF appendix text) |
| **Packaging / quality** | Hatchling build, editable install workflow, optional Ruff + mypy discipline |

---

## Live demo notes

Hosting on **Streamlit Community Cloud** demonstrates product thinking (progressive disclosure, exports, exploratory tabs) quickly for hiring managers and collaborators—while keeping secrets out of the repository. Prefer **least-privilege API tokens**, rate-limit-conscious polling, and clear labelling of artefacts as non-authoritative demos unless wrapped in your organisational validation envelope.

---

## Future roadmap *(signals maturity, not vaporware)*

- **Operational job runner** — Headless Celery or APScheduler façade reusing `DriftDetector.evaluate_with_storage` for nightly portfolio sweeps and Slack / email alerting hooks.
- **Governed configuration UI** — Versioned ontology weight packs persisted as signed JSON artefacts with role-based authoring.
- **Multi-tenant hardening** — Row-level partitioning, KMS-backed SQLite or upstream Postgres adapters, SSO header integration.
- **Authority-specific packs** — Predefined rubrics for RMS vs Ethics vs PV urgency overlays aligned to escalation matrices.
- **Observability** — Structured JSON logging export, OTEL-compatible spans around CTIS transports, anomaly SLIs for ingestion latency regressions.

---

## Project layout

```
app.py                 Streamlit Cloud / docker-friendly entry (`src/` on path → ctis_drift.main)
src/ctis_drift/        Application package (`config`, `main`, `core`, `utils`)
src/ctis_drift/core/   Drift detection, storage, CTIS transport clients
tests/                 Pytest-backed regression coverage (extend as roadmap grows)
data/                  Local SQLite default location (ignored except `.gitkeep`)
.streamlit/            Streamlit chrome & theme defaults (committed; secrets stay in dashboard)
```

---

## Attribution & connect

Architected by **Ela Halilovic** — Regulatory Operations Specialist at the convergence of dossier stewardship, vigilance-aligned operations design, and defensible automation.

| Channel | Purpose |
| :--- | :--- |
| **[LinkedIn →](https://www.linkedin.com/in/ela-halilovic)** | Regulatory Operations delivery portfolios, multidisciplinary programme leadership |
| **[Clinical Future (Substack) →](https://clinicalfuture.substack.com)** | Evidence-led commentary on regulated systems, CTIS-era disclosure pressure, trustworthy tooling |
| **[GitHub →](https://github.com/BouncyMolecules)** | Open engineering experiments and reproducible patterns for life-sciences platforms |

---

## License

Released under the **MIT License**.
