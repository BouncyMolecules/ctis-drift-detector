**CTIS Drift Sentinel**

Substantive change surveillance for EU CTIS public artefacts — built for sponsors, CROs, and vigilance teams who cannot afford silent drift.

Clinical operations intelligence that reads like a cockpit, explains itself like an audit memo, and exports like something you could confidently walk into a Regulatory Affairs review.

**Why this matters**

The EU Clinical Trials Information System (CTIS) has become the single source of truth for trial status, documentation, timelines, authority engagement, and public disclosure. Yet those records are constantly changing — often without proactive notification.

Sponsors and CROs are left reacting to deltas they didn't see coming. Operational teams must translate "something changed somewhere in JSON" into traceable governance: what changed, when, how material it was, and what to do next.

**CTIS Drift Sentinel** is an operations-ready command centre built on cryptographically anchored snapshots and a risk-graded drift engine. It turns raw CTIS payloads into dashboards, timelines, forensic JSON, and audit-ready exports — giving you control before the next inspection or submission deadline.

---

<div align="center">

[**Try live demo**](https://ctis-drift-detector.streamlit.app) · [Quick start](#quick-start) · [Deploy](#deploy-streamlit-community-cloud) · [GxP posture](#gxp-regulatory-compliance)

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://ctis-drift-detector.streamlit.app)

</div>

## What you get (features → outcomes)

- **Portfolio monitoring desk** — One view across enrolled EU CT identifiers: last poll, content fingerprint, drift band, and portfolio counts for trials in elevated bands—the operational signals you need for daily triage.
- **Regulatory-risk scoring** — Deterministic rules (status moves, milestones, queries or RFIs, document churn, authority-facing signals, pharmacovigilance-relevant cues, sponsor and site deltas) roll up to a reproducible LOW → CRITICAL band with explicit rule contributions, not an opaque score.
- **Snapshot lineage** — Canonical JSON hashing avoids duplicate work and anchors “what we saw, when” for governance narratives and evidence packs.
- **Drift history with evidence** — Per-evaluation narrative, sampled changed paths, charts, and downloadable JSON suitable for escalation or filing support.
- **Controlled ingestion** — Retrieve from CTIS, optional pre-baseline drift check, duplicate-hash suppression, and a sandbox JSON path for dry runs or migration.
- **API surface for builders** — Typed search, retrieve, and health envelopes so integrations are not limited to ad hoc scripts.
- **Audit-oriented exports** — Excel (monitoring register, drift archive, document-control sheet) and a text PDF appendix aligned with internal memo-style documentation when refreshed ahead of milestones.

---

## Screenshots

Drop PNG or WebP files under `docs/screenshots/` using the filenames below so README links and previews stay stable. Until assets exist, each caption describes the intended frame.

### 1 · Monitored portfolio — KPI strip and risk-banded registry

![Placeholder: monitored portfolio — headline KPIs, EU CT ID column, colour-coded risk bands, fingerprint column, and last poll time per trial.](docs/screenshots/monitored-portfolio.png)

*Portfolio pulse: where attention should land after the latest poll.*

### 2 · Drift history — lineage and downloadable JSON

![Placeholder: drift history with UTC ordering, expandable evaluation rows, sampled field changes, and control to download full drift JSON.](docs/screenshots/drift-history.png)

*From “something changed” to inspectable evidence without losing the narrative.*

### 3 · Manage trials — retrieval, baseline discipline, sandbox payloads

![Placeholder: EU CT input, retrieve action, baseline and duplicate-hash options, JSON preview, and manual paste area for sandbox or migration JSON.](docs/screenshots/manage-trials.png)

*Ingestion controls that mirror sponsor practice rather than anonymous scraping.*

### 4 · API explorer — typed requests against the public CTIS surface

![Placeholder: base URL context, endpoint selector, parameters, raw JSON response panel, and short guidance on timeouts and response shapes.](docs/screenshots/api-explorer.png)

*A controlled place to probe the public API contract within the same error-handling and UX as the rest of the app.*

---

<a id="try-live-demo"></a>

## Try live demo

The hosted build is a working Streamlit cockpit on [Streamlit Community Cloud](https://streamlit.io/cloud)—use it for walkthroughs, stakeholder reviews, or interview deep-dives without cloning the repository.

| | |
| :--- | :--- |
| **URL** | **[https://ctis-drift-detector.streamlit.app](https://ctis-drift-detector.streamlit.app)** |
| **App entry** | Repository root **`app.py`** (prepends `src/` when needed, then runs `ctis_drift.main`) |
| **Public CTIS base** | [https://euclinicaltrials.eu/ctis-public-api](https://euclinicaltrials.eu/ctis-public-api)—matches `.env.example` and application defaults |

Treat this deployment as **non-validated** unless your organisation wraps it in CSV or equivalent risk assessment, secrets handling, retention policy, and an evidence pack. For production-style use, prefer least-privilege credentials where authentication applies, respectful polling intervals, and durable storage (mounted SQLite or a governed database) if you need history across platform restarts. If Community Cloud assigns a different subdomain after redeploy, update inbound links; this README treats **`ctis-drift-detector.streamlit.app`** as the canonical demo host.

<a id="deploy-streamlit-community-cloud"></a>

## Deploy on Streamlit Community Cloud

The repository is structured so secrets stay in Streamlit **Secrets** (or your vault) and reproducible application code stays in Git.

### Repository layout

| Path | Role |
| :--- | :--- |
| **`app.py`** | Cloud entry: ensures `src/` is on `PYTHONPATH`, then imports `ctis_drift.main` |
| **`requirements.txt`** | Dependency pin file used by Community Cloud (kept aligned with `pyproject.toml`) |
| **`.streamlit/config.toml`** | Theme and UX defaults only (no credentials) |
| **`src/ctis_drift/`** | Application package |

### Deploy checklist

1. Push `app.py`, `requirements.txt`, and `.streamlit/config.toml` on your deployment branch.
2. Open **[share.streamlit.io](https://share.streamlit.io)** and deploy from GitHub.
3. Set **Main file path** to `app.py` and **Requirements file** to `requirements.txt`.
4. Under **Advanced settings**, choose **Python 3.11** when offered (aligned with `requires-python` in `pyproject.toml`).
5. In **Secrets**, provide at least:

   ```toml
   CTIS_API_BASE_URL = "https://euclinicaltrials.eu/ctis-public-api"
   # CTIS_API_TOKEN = "..."   # only if your environment requires bearer auth
   CTIS_DRIFT_DATABASE_URL = "sqlite:///mount/ctis_drift.db"   # or your governed DB URI
   ```

   Do not commit `.streamlit/secrets.toml`; mirror organisational standards in the Cloud UI or your enterprise vault.

6. Deploy. Optionally rename the app subdomain or attach a custom domain so URLs match your programme branding.

**SQLite on Cloud:** locally the default is `sqlite:///data/ctis_drift.db`. On Community Cloud, point `CTIS_DRIFT_DATABASE_URL` at a **writable mount path** or a remote database if persistence must survive restarts.

---

## Quick start

**Prerequisites:** Python **3.11+** (3.11–3.13 are the smoothest on Windows while wheels catch up on newer interpreters), `pip`, and HTTPS egress to your CTIS host (`CTIS_API_BASE_URL`).

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -e .
```

Copy `.env.example` to `.env`. Defaults target the EU CTIS public API at `https://euclinicaltrials.eu/ctis-public-api`; adjust token, timeouts, database URL, logging, and `CTIS_DRIFT_ENABLE_MOCK_API` as needed (`src/ctis_drift/config.py` remains authoritative). Ensure `data/` exists and is writable.

```bash
streamlit run app.py
```

Other entry points:

```bash
streamlit run src/ctis_drift/main.py   # direct Streamlit target after bootstrap-friendly install
ctis-drift-app                         # console script: subprocess to Streamlit on package main.py
```

**Maintainer quality gate**

```bash
pip install -e ".[dev]"
ruff check .
mypy --strict
pytest -q
```

---

## How it works

**For leaders.** The application answers four questions that matter in Regulatory Operations: did the public record move; was the change material; can we show what we knew and when; and can escalation or submissions be briefed with defensible artefacts—dashboards, hashes, narratives, and exports—rather than informal screenshots.

**For builders.**

1. **Transport** (`core.ctis_api`, public client) — `httpx` calls with typed search, retrieve, and health shapes.
2. **Persistence** (`core.storage`) — Trial registry, canonical hashed snapshots, and drift run history via SQLModel and SQLite.
3. **Engine** (`core.drift_detector`) — Structured diffing, regulated signal classes, weighted scoring, `DriftReport`, and auditable rule contributions.
4. **Experience** (`ui`, `cockpit`, `main`) — Streamlit multipage app, Plotly visuals, exports, session state, and operator-facing API error copy.

The drift engine stays independent of the UI so you can reuse it in batch jobs or services where your SDLC requires separation.

---

<a id="gxp-regulatory-compliance"></a>

## GxP / regulatory compliance posture

This repository is a **portfolio-grade reference implementation**: it demonstrates ALCOA-minded surveillance UX and reproducible drift narratives. It is **not** a validated production system until your organisation completes CSV/CSA-style evidence, access control, and change management on **your** deployed stack.

| Pillar | What the codebase emphasises |
| :--- | :--- |
| **Traceability** | UTC-oriented persistence; expandable run detail; exports shaped like monitoring registers. |
| **Integrity cues** | SHA-256 over canonical JSON before diff and scoring; stable snapshot identity for drift narratives. |
| **Human-readable control** | Risk bands, explicit rule contributions, and plain-language summaries instead of opaque model output. |
| **Environment separation** | Configuration via environment variables and `.env`; the UI can surface non-secret context for reproducible reviews. |

Before any regulated reliance: complete risk assessment, identity and access management, retention and monitoring, incident handling, change control for ontology and scoring updates, and Annex 11 / CSA-aligned validation on the environment you operate—not on this template alone.

---

## Technology stack

| Layer | Choices |
| :--- | :--- |
| **Experience** | Streamlit, Plotly, cockpit-oriented layout |
| **Typing** | Python 3.11+, Pydantic v2 models across API and drift domains |
| **Persistence** | SQLite and SQLModel for workstation-scale audit logs |
| **HTTP** | `httpx` with explicit error taxonomy |
| **Exports** | `openpyxl`, `fpdf2` |
| **Packaging / QA** | Hatchling, Ruff, mypy `--strict`, pytest |

---

## Future roadmap *(concrete directions)*

- **Headless runner** — Scheduled portfolio sweeps via the same detector hooks, with optional Slack or email integration.
- **Governed configuration** — Versioned, signed weight and ontology packs with role-aware editing.
- **Multi-tenant hardening** — Partitioning, KMS-ready storage backends, enterprise IdP integration.
- **Authority packs** — Pre-shaped rubrics for RMS, ethics, or pharmacovigilance escalation matrices.
- **Observability** — Structured logs and tracing around CTIS latency and failure modes.

---

## Project layout

```
app.py                 Streamlit / Cloud entry (imports ctis_drift.main)
src/ctis_drift/        Package root: config, cockpit, main, core, ui, utils
src/ctis_drift/core/   Drift engine, storage, CTIS clients
tests/                 Pytest suite
data/                  Default SQLite directory (.gitkeep in repo)
.streamlit/            Theme defaults (no secrets committed)
docs/screenshots/      Optional UI captures referenced by README
```

---

## Connect

**Ela Halilovic** — Regulatory Operations and digital transformation at the intersection of dossier stewardship, vigilance-aligned operations design, and disciplined automation.

- [LinkedIn](https://www.linkedin.com/in/ela-halilovic)
- [Clinical Future (Substack)](https://clinicalfuture.substack.com)
- [GitHub](https://github.com/BouncyMolecules)

---

## License

Released under the **MIT License**.
