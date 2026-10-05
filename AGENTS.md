# AGENTS.md: briefing for AI coding assistants

TrialBridge is a capstone project: explainable clinical-trial ↔ patient matching. Free-text eligibility criteria are
parsed into predicates, which are evaluated deterministically against patient profiles. See `README.md` for the full
picture. This file covers what you need to change code safely.

## Commands (run from `backend/`)

```bash
uv sync                              # install
uv run pytest -q                     # tests: must stay green (currently 20)
uv run trialbridge serve --reload    # API + built UI on :8000
uv run trialbridge parse             # after parser/vocab changes: re-parse DB, check coverage in results/
uv run trialbridge index --no-dense  # fast BM25-only index for dev (dense takes ~15 min for 2.7k trials on CPU)
uv run trialbridge trec-eval --limit 10 --db ../data/trec/trec.db   # quick benchmark smoke test
```

Frontend (`frontend/`): `npm run dev` (port 5173, proxies `/api` to :8000), `npm run build`, and type-check
with `npx tsc -b`.

## Architecture in one pass

`ingest/ctgov.py` → `db.py` (SQLite: `trials`, `criteria`, `patients`) → `criteria/parser.py` (uses `vocab.py`) →
`patients/profile.py` → `matching/retrieval.py` (BM25 + dense + RRF) → `matching/evaluator.py` → `matching/engine.py`
(`Matcher`) → `api.py` (FastAPI) → `frontend/`.

Core data shapes (plain dicts/JSON, no ORM):

* **Criterion**: `{"kind": "inclusion"|"exclusion", "text": str, "predicates": [ ... ]}`
* **Predicate**: has `type` ∈ `age | sex | lab | condition | medication | covered | unparsed`, plus type-specific keys
  (`concept`, `lab`, `op`, `value`, `unit`, `negated`, `within_days`, `status`). Most have `span: [start, end]` into
  `text`, which the UI uses for highlighting, so keep spans correct. `unparsed` with `partial: True` means "some rules
  were extracted but the remainder is not understood".
* **Patient profile**: `{"age", "sex", "conditions": [{"concept","display","onset","active"}], "medications": [...],
  "labs": {key: {"value","unit","date"}}, "negated": [concept keys], "closed_world": bool, "summary"}`.
* **Evaluation status** per criterion: inclusion → `met | not_met | unknown`; exclusion → `excluded | clear |
  unknown`; plus `covered` (handled by the registry age field).

## Invariants: don't break these

1. **Three-valued (Kleene) logic.** Missing data is `unknown`, never `false`. Don't "simplify" it to booleans.
2. **Closed world only when `profile["closed_world"]` is true** (Synthea). Free-text patients are open world.
3. **Acute concepts** (`Concept.acute=True`: pregnancy, sepsis, COVID-19) match only active episodes unless the
   criterion says "history of" / has a time window.
4. **Partial parses** can produce `not_met` / `excluded`, but never `met` / `clear`.
5. **Every explanation must be traceable**: a reason string cites the patient's value and the threshold.
6. Tests in `backend/tests/` describe intended behaviour. Add a test for every new parsing rule or evaluator case.

## Conventions

* Python 3.11, type hints, small pure functions, no new heavy dependencies without a reason. Regexes in `vocab.py`
  are lowercase and matched case-insensitively.
* Paths come from `config.py`, never hard-code machine paths.
* Lab values are normalised to the canonical unit in `vocab.LABS` (e.g. creatinine to mg/dL); conversions live there.
* Frontend: React 18 + TypeScript + Tailwind 4 utility classes; API calls only through `src/api.ts`.
* Commit messages: one line with a prefix: `feat:`, `fix:`, `test:`, `docs:`, `dataset:`, `refactor:`, `chore:`.

## Pitfalls already hit (don't rediscover them)

* ClinicalTrials.gov stores criteria as Markdown: `\<`, `\>=` are unescaped at the top of `parse_eligibility`.
* Criteria headers can carry content inline ("Inclusion Criteria: 18 years, …"), and the header regex keeps it.
* Windows without symlink rights breaks the Hugging Face cache, so models are downloaded with `local_dir` into
  `.cache/models/` (`retrieval.model_path`).
* `transformers` will import a system-wide TensorFlow if one exists. `config.py` sets `USE_TF=0` before any import.
* Synthea emits social "findings" (employment, education) as Conditions; `profile.py` filters them out.
* BP comes as a panel (LOINC 85354-9) with systolic/diastolic as *components*.
* Dense indexing is slow on CPU. Use `--no-dense` while iterating, and the full index only for final numbers.

## Phase 2 work in progress

CTRI scraper, Ollama LLM layer for `unparsed` predicates, scispaCy/UMLS linking, n2c2 2018 evaluation.
See README §12. Team members are building these themselves to learn, so when asked for help on Phase 2,
prefer explaining and reviewing over writing whole modules, unless the person asks you to write it.
