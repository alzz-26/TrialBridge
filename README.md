# TrialBridge

**AI-assisted clinical trial and volunteer matching system.**

TrialBridge reads a patient's record and the eligibility rules of thousands of clinical trials. It suggests the trials
that patient can actually join and explains **why**, rule by rule. It also works in reverse: pick a trial and it
screens a whole patient cohort.

The core idea: free-text eligibility criteria are **parsed into executable rules**, e.g.
`age 18-75 AND HbA1c 7-10.5% AND eGFR > 45 AND NOT (myocardial infarction within 183 days)`.
These rules are then evaluated deterministically against the patient. Every ✓ / ✗ / ? traces back to a span of the
original criteria text, so a clinician can audit it. Rules that are too vague to parse are flagged for an LLM layer
(Phase 2) instead of being guessed.

> New to the project, or explaining it to non-technical people? Read
> [docs/TrialBridge_Explained_Simply.pdf](docs/TrialBridge_Explained_Simply.pdf) first.

---

## Contents

1. [Quick start (just run the demo)](#1-quick-start-just-run-the-demo)
2. [What you see](#2-what-you-see)
3. [How it works](#3-how-it-works)
4. [Repository layout](#4-repository-layout)
5. [Developer setup](#5-developer-setup)
6. [CLI reference](#6-cli-reference)
7. [Rebuilding the data from scratch](#7-rebuilding-the-data-from-scratch)
8. [API reference](#8-api-reference)
9. [Results](#9-results)
10. [Configuration](#10-configuration)
11. [Troubleshooting](#11-troubleshooting)
12. [Roadmap (Phase 2)](#12-roadmap-phase-2)
13. [Working with AI coding assistants](#13-working-with-ai-coding-assistants)

---

## 1. Quick start (just run the demo)

**Needs:** Windows / macOS / Linux, internet on first run, ~5 GB free disk.
You do **not** need Node.js, Java or a separate Python install to run the demo.

**Step 1: install [uv](https://docs.astral.sh/uv/)** (it installs Python and all packages for you):

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then close and reopen your terminal.

**Step 2: clone the repo.**

```bash
git clone https://github.com/alzz-26/TrialBridge.git
cd TrialBridge
```

**Step 3: get the demo data.** The database, search index and pre-built UI are kept out of git, because they are
binary files that can be regenerated. They are published as a release asset instead.

*Windows: just double-click `start.bat`.* It downloads the data if it is missing, installs everything, starts the
server and opens the browser. You're done.

Or do it by hand (any OS):

```bash
curl -L -o data.zip https://github.com/alzz-26/TrialBridge/releases/download/v0.1.0/trialbridge-demo-data.zip
tar -xf data.zip          # creates data/trialbridge.db, data/index/main/, frontend/dist/
rm data.zip
```

**Step 4: run.**

```bash
cd backend
uv sync                   # first time only, ~1 GB download (PyTorch etc.)
uv run trialbridge serve
```

Open **http://localhost:8000**. On first start the server downloads the PubMedBERT model (~440 MB) into `.cache/`,
so give it a minute. Stop the server with `Ctrl+C`.

**Check that everything works:**

```bash
cd backend
uv run pytest -q          # expect: 20 passed
```

## 2. What you see

| Screen | What it does |
|---|---|
| **Patient → Trials** | Pick one of 300 synthetic patients, or type one (*"62-year-old man with type 2 diabetes on metformin, HbA1c 8.4, eGFR 58"*). You get ranked trials labelled **Eligible / Possibly eligible / Ineligible**. Click **Why?** to see each criterion with the patient's value and the threshold. |
| **Trial → Patients** | Recruiter view. Search for a trial and the whole cohort is screened against its parsed criteria (~1 s). |
| **Criteria Parser** | Paste any eligibility text (or load an NCT id). Highlighted spans show exactly which words became which rule. Unparsed criteria are marked "LLM residue". |
| **Evaluation** | TREC Clinical Trials 2021 benchmark tables and parser coverage statistics. |

Interactive API docs: http://localhost:8000/docs

## 3. How it works

```
 ClinicalTrials.gov API v2 ──► Ingestion & normalisation ──► SQLite (trials, criteria, patients)
 (CTRI scraper: Phase 2)             │                               ▲
                                     ▼                               │
                          Criteria parser ───── predicates ──────────┤
                          (sections, bullets, labs + units,          │
                           age, conditions, meds, negation,          │
                           temporal windows, ULN multipliers,        │
                           residual "unparsed" detection)            │
                                                                     │
 Synthea FHIR bundles ──► Patient representation (FHIR → profile) ───┘
 or free-text patient                │
                                     ▼
   query ──► Hybrid retrieval: BM25 + PubMedBERT dense, fused with RRF ── top-100 candidates
                                     │
                                     ▼
          Deterministic evaluator (3-valued Kleene logic: true / false / unknown)
          score = 0.4 · retrieval + 0.6 · eligibility ──► ranked, explained matches
          (LLM on the unparsed residue: Phase 2, Ollama)
                                     │
                       FastAPI  ◄────┴────►  React + Tailwind UI
```

Key design decisions (useful for viva / Q&A):

* **Rules first, LLM last.** Most criteria (ages, lab thresholds, diagnoses, medications) are handled by transparent
  rules. That is cheap, fast, reproducible and cannot hallucinate. The LLM is reserved for the vague residue.
* **Three-valued logic.** Missing data gives *unknown*, not *false*. Trials are labelled *possibly eligible* rather
  than silently dropped or wrongly approved.
* **Closed-world only for structured records.** For Synthea (coded FHIR), "no record of X" means the patient doesn't
  have X. For free text it means *unknown*, unless the text explicitly negates it ("no history of heart failure").
* **Acute vs chronic.** Exclusions like pregnancy, sepsis or COVID-19 only match an *active* episode, unless the
  criterion says "history of".
* **Partial parses are flagged.** If a criterion yields some rules but leaves more than 6 unexplained content words,
  it gets an `unparsed (partial)` predicate. It can still definitively fail, but it can never count as fully met.

The five modules map to the five team members:

| # | Module | Code |
|---|---|---|
| 1 | Trial ingestion & data platform | `backend/src/trialbridge/ingest/ctgov.py`, `db.py` |
| 2 | Criteria understanding | `backend/src/trialbridge/criteria/parser.py`, `vocab.py` |
| 3 | Patient representation | `backend/src/trialbridge/patients/profile.py` |
| 4 | Matching & reasoning | `backend/src/trialbridge/matching/` (`retrieval.py`, `evaluator.py`, `engine.py`) |
| 5 | Evaluation & product | `backend/src/trialbridge/eval/trec.py`, `api.py`, `frontend/` |

## 4. Repository layout

```
TrialBridge/
├── start.bat                    # Windows one-click: data download + install + run
├── backend/
│   ├── pyproject.toml, uv.lock  # Python deps (managed by uv)
│   ├── src/trialbridge/
│   │   ├── config.py            # paths, model name, env-var overrides
│   │   ├── db.py                # SQLite schema + helpers
│   │   ├── vocab.py             # concept lexicon: conditions, medications, labs (LOINC), units
│   │   ├── cli.py               # `trialbridge <command>` entry point
│   │   ├── api.py               # FastAPI app (also serves frontend/dist)
│   │   ├── ingest/ctgov.py      # ClinicalTrials.gov API v2 client + normaliser
│   │   ├── criteria/parser.py   # eligibility text → predicates
│   │   ├── patients/profile.py  # Synthea FHIR / free text → patient profile
│   │   ├── matching/
│   │   │   ├── retrieval.py     # BM25 + dense + RRF hybrid index
│   │   │   ├── evaluator.py     # predicate evaluation, Kleene logic, explanations
│   │   │   └── engine.py        # Matcher: patient→trials, trial→patients
│   │   └── eval/trec.py         # TREC CT 2021 benchmark harness
│   └── tests/                   # pytest: parser, evaluator, FHIR loader
├── frontend/                    # React 18 + TypeScript + Vite + Tailwind 4
│   └── src/pages/               # PatientMatch, Recruiter, Parser, Evaluation
├── data/                        # (git-ignored) DBs, indexes, Synthea output
│   └── trec/                    # TREC 2021 topics + qrels (committed, small)
├── results/                     # benchmark + parser-coverage JSON (committed)
└── docs/                        # plain-language explainer PDF, Review-2 guide
```

## 5. Developer setup

Requirements: **uv** (always), **Node 20+** (only to edit the UI), **Java 11+** (only to regenerate Synthea patients).

```bash
# backend
cd backend
uv sync
uv run pytest -q

# frontend with hot reload (in a second terminal, while the backend is running)
cd frontend
npm install
npm run dev               # http://localhost:5173, proxies /api to :8000
```

After changing the UI, run `npm run build`. The backend then serves the new `frontend/dist/` on :8000.

Useful during backend work:

```bash
uv run trialbridge serve --reload     # auto-restart on code changes
```

## 6. CLI reference

Run from `backend/` as `uv run trialbridge [--db PATH] <command>`. `--db` defaults to `data/trialbridge.db`.

| Command | What it does | Main options |
|---|---|---|
| `ingest` | Fetch trials from ClinicalTrials.gov into the DB | `--conditions "Diabetes;Asthma"`, `--per 150` (per condition), `--status RECRUITING` |
| `synthea` | Generate synthetic patients with Synthea and load them | `--n 300`, `--seed 42`, `--ages 25-85`, `--skip-generate` (reload existing output) |
| `parse` | Re-parse all criteria; writes `results/parse_stats_<db>.json` | |
| `index` | Build the search index | `--name main`, `--no-dense` (BM25 only, seconds), `--max-seq 256`, `--batch 32` |
| `trec-fetch` | Download the ~26k trials judged in TREC 2021 | use with `--db ../data/trec/trec.db` |
| `trec-eval` | Run the benchmark; writes `results/trec2021.json` | `--name trec`, `--settings rerank,corpus`, `--limit N` (first N topics) |
| `serve` | Start API + UI | `--port 8000`, `--host 127.0.0.1`, `--reload` |

## 7. Rebuilding the data from scratch

Only needed if you change ingestion, parsing or the patient loader, or want fresh trials. From `backend/`:

```bash
# demo corpus (~30-60 min on a laptop CPU, mostly the dense index)
uv run trialbridge ingest --per 150      # ~2.8k recruiting trials across 20 conditions
uv run trialbridge synthea --n 300       # needs Java + tools/synthea.jar (below)
uv run trialbridge parse
uv run trialbridge index --name main

# TREC benchmark (~1.5 h, mostly embedding 26k trials)
uv run trialbridge --db ../data/trec/trec.db trec-fetch
uv run trialbridge --db ../data/trec/trec.db parse
uv run trialbridge --db ../data/trec/trec.db index --name trec --max-seq 128 --batch 64
uv run trialbridge --db ../data/trec/trec.db trec-eval
```

Synthea: download `synthea-with-dependencies.jar` from
<https://github.com/synthetichealth/synthea/releases> and save it as `tools/synthea.jar`.

Tip: `index --no-dense` builds a BM25-only index in seconds. The app works with it (hybrid search falls back to BM25).

**Publishing a new demo data bundle** (maintainer): zip `data/trialbridge.db`, `data/index/main/` and `frontend/dist/`
(paths relative to the repo root) as `trialbridge-demo-data.zip`, and attach it to a new GitHub release.

## 8. API reference

Full interactive docs at `/docs`. Main endpoints:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health`, `/api/stats` | status; corpus / cohort counts |
| GET | `/api/trials?q=…` | search trials |
| GET | `/api/trials/{nct_id}` | trial with parsed criteria |
| GET | `/api/patients`, `/api/patients/{id}` | synthetic cohort |
| POST | `/api/match/patient` | body `{"patient_id": …}` or `{"text": "…"}`, plus optional `mode` (`bm25`/`dense`/`hybrid`) → ranked, explained trials |
| GET | `/api/match/trial/{nct_id}` | screen the cohort for one trial |
| POST | `/api/parse` | body `{"text": "…"}` → criteria with predicates and spans |
| GET | `/api/vocab`, `/api/eval` | lexicon; saved benchmark results |

## 9. Results

TREC Clinical Trials 2021: 75 patient topics, 35,832 graded judgements. P@10 counts *eligible* trials only.

**Re-ranking each topic's judged pool**

| System | NDCG@10 | P@10 | Recall@100 | MRR |
|---|---|---|---|---|
| BM25 | 0.404 | 0.263 | 0.343 | 0.477 |
| Dense (PubMedBERT) | 0.466 | 0.351 | 0.451 | 0.580 |
| Hybrid (RRF) | 0.444 | 0.312 | 0.425 | 0.537 |
| **Hybrid + criteria evaluator** | **0.548** | **0.445** | 0.425 | **0.719** |

**Retrieval from all 26,158 judged trials**

| System | NDCG@10 | P@10 | Recall@100 | MRR |
|---|---|---|---|---|
| BM25 | 0.396 | 0.255 | 0.266 | 0.474 |
| Dense (PubMedBERT) | 0.343 | 0.253 | 0.276 | 0.481 |
| Hybrid (RRF) | 0.407 | 0.276 | 0.322 | 0.526 |
| **Hybrid + criteria evaluator** | **0.442** | **0.355** | 0.322 | **0.595** |

The deterministic evaluator adds **+43% P@10** over hybrid retrieval (pool setting) with no LLM. Recall@100 doesn't
change, because the evaluator only re-orders the shortlist.

Parser coverage on 26k real trials: 38.7% of free-text criteria yield at least one executable rule, and 22.5% are
fully parsed. The rest is the residue for the Phase-2 LLM layer.

Caveats: trial records are fetched live (current versions), while the judgements were made on a 2021 snapshot. The
benchmark index truncates trial text to 128 tokens.

## 10. Configuration

Environment variables (all optional):

| Variable | Default | Meaning |
|---|---|---|
| `TB_DATA_DIR` | `data/` | where DBs and indexes live |
| `TB_DB_PATH` | `data/trialbridge.db` | main SQLite DB |
| `TB_EMBED_MODEL` | `NeuML/pubmedbert-base-embeddings` | sentence-transformers model for dense retrieval |
| `HF_HOME` | `.cache/hf` | Hugging Face cache (models themselves go to `.cache/models/`) |

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| `uv` not recognised | Install it (step 1) and **reopen** the terminal |
| Port 8000 already in use | Another copy is running: close it, or `uv run trialbridge serve --port 8001` |
| `uv sync` slow or times out | Run it again (it resumes). Optionally `set UV_HTTP_TIMEOUT=300` |
| Blank page at :8000 | `frontend/dist/` is missing: get the data bundle, or `cd frontend && npm install && npm run build` |
| "no such table" / 0 trials | `data/trialbridge.db` is missing: get the data bundle (step 3) |
| Windows symlink / privilege error from Hugging Face | Already handled: models download into `.cache/models/` as plain folders |
| Low disk space or out-of-memory during install | PyTorch needs ~1 GB plus space for the page file; keep 10 GB free on the system drive |
| Dense indexing very slow | Expected on CPU (~1 h for 26k trials). Use `--max-seq 128`, or `--no-dense` while developing |

## 12. Roadmap (Phase 2)

| Item | Module | Notes |
|---|---|---|
| CTRI scraper (Indian registry) | 1 | Same `trials` schema as ClinicalTrials.gov; `source` column already exists |
| LLM reasoning on unparsed / partial criteria | 4 | Ollama + Llama 3.1 8B / Mistral 7B, JSON-constrained output, must quote patient evidence |
| UMLS / SNOMED / RxNorm normalisation | 2 | scispaCy entity linking to replace the regex lexicon in `vocab.py` |
| n2c2 2018 Track 1 evaluation | 5 | Criterion-level precision / recall (data needs a DUA) |
| Ablation: rules-only vs LLM-only vs hybrid | 5 | TrialGPT-style LLM baseline |
| PostgreSQL + Qdrant + Docker Compose | 1 | Deployment |

## 13. Working with AI coding assistants

This repo includes [`AGENTS.md`](AGENTS.md), a briefing for AI assistants (Claude Code, Cursor, Copilot, Codex…).
It covers architecture, commands, conventions and known pitfalls. Claude Code reads it automatically via `CLAUDE.md`.
For other tools, ask the assistant to "read AGENTS.md first".

Tips for teammates:
* Ask the assistant to run `uv run pytest -q` after every change, and to add a test for any new parsing rule.
* Point it at the module you own (section 3) instead of the whole repo. It works better with a narrow scope.
* Make sure you understand what it writes. You'll be asked about your module in reviews.

Commit messages: one line with a type prefix, e.g. `feat: add CTRI search page scraper`, `fix: handle missing
eGFR unit`, `test: cover pregnancy history case`, `docs: …`, `dataset: …`, `chore: …`.

---

Data sources: [ClinicalTrials.gov](https://clinicaltrials.gov) (public), [Synthea](https://synthetichealth.github.io/synthea/)
(synthetic, no real patient data), [TREC Clinical Trials 2021](https://www.trec-cds.org/2021.html),
n2c2 2018 (DUA, Phase 2), CTRI (Phase 2). This is an academic project. It is not a medical device and does not replace
clinical judgement.
