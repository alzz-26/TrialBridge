"""Two-stage matcher, both directions.

patient -> trials : hybrid retrieval narrows 100k+ trials to ~100 candidates,
                    then the deterministic evaluator checks every criterion.
trial -> patients : (recruiter view) evaluate the trial's criteria against the
                    whole cohort, rank by eligibility then relevance.

final_score = W_RETRIEVAL * normalised retrieval score + W_ELIGIBILITY * eligibility score
"""

import json
from functools import lru_cache

from trialbridge import db
from trialbridge.matching.evaluator import eval_trial
from trialbridge.matching.retrieval import HybridIndex
from trialbridge.vocab import CONCEPT_BY_KEY

W_RETRIEVAL, W_ELIGIBILITY = 0.4, 0.6
VERDICT_ORDER = {"eligible": 0, "possibly_eligible": 1, "ineligible": 2}


def patient_query(p: dict) -> str:
    """Retrieval query for a patient: mapped chronic conditions first, then everything else."""
    if p.get("source_text"):
        return p["source_text"]
    active = [c for c in p["conditions"] if c.get("active", True)]
    mapped = sorted({CONCEPT_BY_KEY[c["concept"]].label for c in active if c.get("concept") in CONCEPT_BY_KEY})
    displays = sorted({c["display"] for c in active if c.get("concept")})
    sex = {"MALE": "male", "FEMALE": "female"}.get(p.get("sex") or "", "")
    age = f"{p['age']:.0f} year old" if p.get("age") is not None else ""
    return f"{age} {sex} patient with {', '.join(mapped)}. {'. '.join(displays)}"


class Matcher:
    def __init__(self, index_name: str = "main"):
        with db.session() as conn:
            self.trials = {r["trial_id"]: db.row_to_dict(r) for r in conn.execute("SELECT * FROM trials")}
            self.criteria: dict[str, list[dict]] = {}
            for r in conn.execute("SELECT * FROM criteria ORDER BY trial_id, position"):
                d = db.row_to_dict(r)
                self.criteria.setdefault(d["trial_id"], []).append(
                    {"kind": d["kind"], "text": d["text"], "predicates": d["predicates"],
                     **({"structured": True} if "(registry field)" in d["text"] else {})})
            self.patients = {r["patient_id"]: db.row_to_dict(r) for r in conn.execute("SELECT * FROM patients")}
        try:
            self.index = HybridIndex.load(index_name, self.trials)
        except FileNotFoundError:
            self.index = HybridIndex.build(list(self.trials.values()), dense=False) if self.trials else None

    # ------------------------------------------------------------------ helpers
    def trial_card(self, tid: str) -> dict:
        t = self.trials[tid]
        return {k: t.get(k) for k in ("trial_id", "source", "title", "status", "phase", "conditions", "interventions",
                                       "min_age_years", "max_age_years", "sex", "countries", "summary")}

    # ------------------------------------------------------------------ patient -> trials
    def match_patient(self, profile: dict, k: int = 20, candidates: int = 100, mode: str = "hybrid",
                      recruiting_only: bool = False) -> dict:
        query = patient_query(profile)
        subset = [t for t, v in self.trials.items() if v.get("status") == "RECRUITING"] if recruiting_only else None
        hits = self.index.search(query, k=candidates, mode=mode, subset=subset)
        if not hits:
            return {"query": query, "results": []}
        top = hits[0][1]
        results = []
        for rank, (tid, rscore, ranks) in enumerate(hits, 1):
            ev = eval_trial(self.criteria.get(tid, []), profile)
            r_norm = rscore / top if top else 0
            final = W_RETRIEVAL * r_norm + W_ELIGIBILITY * ev["score"]
            results.append({"trial": self.trial_card(tid), "retrieval_rank": rank, "retrieval_score": round(r_norm, 4),
                            **ranks, "final_score": round(final, 4), **ev})
        results.sort(key=lambda r: (VERDICT_ORDER[r["verdict"]], -r["final_score"]))
        return {"query": query, "results": results[:k]}

    # ------------------------------------------------------------------ trial -> patients
    def match_trial(self, trial_id: str, k: int = 50) -> dict:
        crit = self.criteria.get(trial_id, [])
        out = []
        for pid, row in self.patients.items():
            ev = eval_trial(crit, row["profile"])
            out.append({"patient_id": pid, "name": row["name"], "age": row["profile"].get("age"),
                        "sex": row["profile"].get("sex"), **ev})
        out.sort(key=lambda r: (VERDICT_ORDER[r["verdict"]], -r["score"]))
        counts = {v: sum(r["verdict"] == v for r in out) for v in VERDICT_ORDER}
        return {"trial": self.trial_card(trial_id), "cohort_size": len(out), "counts": counts, "results": out[:k]}


@lru_cache(maxsize=1)
def get_matcher() -> Matcher:
    return Matcher()


def dumps(obj) -> str:
    return json.dumps(obj, default=str)
