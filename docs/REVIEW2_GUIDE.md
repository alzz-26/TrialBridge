# TrialBridge: Phase 1 / Review 2 Guide

## 1. What to have ready for Review 2

Review 2 (Phase 1) is marked on: **written report 15 · presentation 10 · team collaboration 10 ·
component demo 10 · Q&A 5**. It is not an ML-only review. The panel wants to see each *component*
working and a report describing it.

The PDF's Phase-1 target was:

| Phase-1 deliverable (from the idea portfolio) | Status |
|---|---|
| Ingestion pipeline live for ClinicalTrials.gov | ✅ API v2 client, schema normaliser, SQLite. 2,766 recruiting trials (demo) + 26,158 trials (benchmark) |
| Synthea cohort generated | ✅ 300 synthetic adults (FHIR R4) → normalised patient profiles |
| Baseline matcher working end to end | ✅ BM25 + PubMedBERT dense + RRF hybrid, plus a deterministic criteria evaluator |
| Initial evaluation numbers | ✅ TREC Clinical Trials 2021 (75 topics, 35,832 judgements). n2c2 needs a DUA (see §6) |
| Basic UI | ✅ React app with 4 screens: patient→trials, trial→patients, criteria parser, evaluation |

Also done ahead of schedule: the **structured-predicate parser**, which the PDF had planned for Phase 2.
That is your differentiator, so it's worth having early.

## 2. Demo script (≈ 6 minutes)

Start: double-click `start.bat` (or run `cd backend`, then `uv run trialbridge serve`), then open http://localhost:8000.

1. **Criteria Parser tab** (Module 2). Click *Parse criteria* on the sample. Point at the highlights:
   `eGFR > 45` becomes `egfr > 45 mL/min/1.73m²`, "within 6 months" becomes `≤ 183d`, and "3 x ULN" becomes `ALT > 120 U/L`.
   The last criterion ("investigator opinion") is kept as **LLM residue**, the hand-off point for Phase 2.
   Load a real trial by NCT id to show it isn't hard-coded.
2. **Patient → Trials tab**, *Describe a patient* (Modules 3+4). Run the default text. Show the profile chips
   (labs extracted from free text, struck-through negated conditions), then expand *Why?* on a result. Every ✓/✗/? cites
   the patient's value and the threshold.
3. Same tab, *Synthea cohort*. Pick a patient with CKD or diabetes. These are structured FHIR records,
   so the evaluator can decide many more criteria.
4. **Trial → Patients tab** (recruiter view, the bidirectional differentiator). Search "type 2 diabetes", pick a
   trial, and the whole cohort is screened in about a second.
5. **Evaluation tab** (Module 5). Show the TREC table: adding the criteria evaluator lifts P@10 from 0.312 to 0.445
   over hybrid retrieval (§3).

## 3. Results to quote

TREC Clinical Trials 2021, 75 patient topics (`results/trec2021.json`, also shown live on the Evaluation tab).

**Setting A: re-rank each topic's judged pool** (same setup as TrialGPT-Ranking)

| System | NDCG@10 | P@10 (eligible) | Recall@100 | MRR |
|---|---|---|---|---|
| BM25 | 0.404 | 0.263 | 0.343 | 0.477 |
| Dense (PubMedBERT) | 0.466 | 0.351 | 0.451 | 0.580 |
| Hybrid (BM25 + dense, RRF) | 0.444 | 0.312 | 0.425 | 0.537 |
| **TrialBridge: hybrid + criteria evaluator** | **0.548** | **0.445** | 0.425 | **0.719** |

**Setting B: retrieve from all 26,158 judged trials**

| System | NDCG@10 | P@10 (eligible) | Recall@100 | MRR |
|---|---|---|---|---|
| BM25 | 0.396 | 0.255 | 0.266 | 0.474 |
| Dense (PubMedBERT) | 0.343 | 0.253 | 0.276 | 0.481 |
| Hybrid (BM25 + dense, RRF) | 0.407 | 0.276 | 0.322 | 0.526 |
| **TrialBridge: hybrid + criteria evaluator** | **0.442** | **0.355** | 0.322 | **0.595** |

Key claims:
* The deterministic eligibility layer adds **+43% P@10** (0.312 → 0.445) and **+23% NDCG@10** over hybrid retrieval in
  setting A, and +29% P@10 in setting B, **with no LLM at all**.
* Recall@100 is identical with and without the evaluator, because it only re-orders the top 100. The gain comes
  purely from moving *eligible* trials above merely *topical* ones. That is the point of parsing criteria.
* Hybrid fusion beats either retriever alone on the harder full-corpus setting (B).

Setup details for the report: dense encoder `NeuML/pubmedbert-base-embeddings`, trial text truncated to 128 tokens for
the benchmark index (256 for the demo index), RRF k = 60, final score = 0.4 · retrieval + 0.6 · eligibility, with the
evaluator re-ranking the hybrid top 100.

Criteria parser on 26k real trials: ~39–42% of free-text criteria yield at least one executable predicate, and ~25% are
fully machine-readable. The remainder is exactly the "ambiguous residue" the Phase-2 LLM layer is designed for.
That's a good Q&A answer, because it quantifies why a hybrid rules + LLM design is needed.

Caveats to state honestly (panels respect it):
* Trial records are fetched live (2026 versions), while TREC judgements were made on an April-2021 snapshot.
* The evaluator gives "unknown" when data is missing, rather than guessing. Synthea records use a closed-world
  assumption (no record of a condition means the patient doesn't have it); free text does not.

## 4. Five-member split (who presents what)

| Member | Module | Code | Review-2 talking points |
|---|---|---|---|
| 1 | Trial ingestion & data platform | `ingest/ctgov.py`, `db.py`, `cli.py ingest` | API v2, pagination/retry, schema normalised for CTRI, 29k trials stored |
| 2 | Criteria understanding | `criteria/parser.py`, `vocab.py` | section/bullet splitting, labs + unit conversion, ULN, NegEx, temporal windows, residual detection |
| 3 | Patient representation | `patients/profile.py` | Synthea → FHIR → profile, LOINC lab mapping, BP panel components, free-text patient extraction |
| 4 | Matching & reasoning | `matching/retrieval.py`, `evaluator.py`, `engine.py` | BM25 + PubMedBERT + RRF, Kleene 3-valued logic, scoring, explanations |
| 5 | Evaluation & product | `eval/trec.py`, `api.py`, `frontend/` | TREC harness + ablations, FastAPI, React UI |

Each member should be able to run `pytest` and explain at least one test in `backend/tests/`, which helps with the
"team collaboration" marks.

## 5. Phase 2 roadmap (Reviews 3–4)

1. **CTRI scraper** (Member 1): Indian registry ingestion into the same `trials` schema, which is the India-focused novelty.
2. **LLM reasoning on residue** (Member 4): Ollama + Llama 3.1 8B / Mistral 7B, applied *only* to `unparsed` / `partial`
   criteria, with JSON-constrained output and a hallucination guard (the answer must quote the patient record).
3. **UMLS/SNOMED/RxNorm normalisation** (Member 2): replace the regex lexicon in `vocab.py` with scispaCy + UMLS linking.
4. **n2c2 2018 Track 1** criterion-level evaluation (Member 5): per-criterion precision/recall of the parser + evaluator.
5. TrialGPT-style LLM-only baseline and an ablation of rules-only vs LLM-only vs hybrid.
6. PostgreSQL + Qdrant + Docker Compose, then deploy.

## 6. What *you* need to do

* **Apply for n2c2 2018 data now** (free DUA, takes days to weeks): https://portal.dbmi.hms.harvard.edu/ → register → request "n2c2 NLP Research Data Sets".
* **Free space on C:** (it was at 0 bytes, which broke installs and memory). Keep 10+ GB free. Ollama models for Phase 2 need ~5 GB.
* **Phase 2 only:** install Ollama (https://ollama.com/download), then `ollama pull llama3.1:8b`.
* Read and cite: TrialGPT (Jin et al., *Nat. Commun.* 2024), Criteria2Query (Yuan et al., *JAMIA* 2019),
  TREC CT 2021 overview (Roberts et al.), NegEx (Chapman et al. 2001), RRF (Cormack et al. 2009), Synthea (Walonoski et al. 2018).
