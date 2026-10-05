"""FastAPI backend for the TrialBridge UI."""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from trialbridge import config
from trialbridge.criteria.parser import parse_eligibility, parse_stats
from trialbridge.matching.engine import get_matcher
from trialbridge.patients.profile import from_text, summarise
from trialbridge.vocab import CONCEPT_BY_KEY, LAB_BY_KEY, LABS

@asynccontextmanager
async def lifespan(_: FastAPI):
    # warm up: load DB + index + encoder now, so the first demo query is not a 30 s wait
    m = get_matcher()
    if m.index is not None:
        m.index.search("warm up", k=1)
    yield


app = FastAPI(title="TrialBridge API", version="0.1.0", lifespan=lifespan,
              description="Explainable clinical trial matching - patient->trials and trial->patients.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _patient_brief(row: dict) -> dict:
    p = row["profile"]
    conds = sorted({c["concept"] for c in p["conditions"] if c.get("concept") and c.get("active", True)})
    return {"patient_id": row["patient_id"], "name": row["name"], "age": p.get("age"), "sex": p.get("sex"),
            "conditions": [CONCEPT_BY_KEY[c].label for c in conds if c in CONCEPT_BY_KEY]}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stats")
def stats():
    m = get_matcher()
    statuses: dict[str, int] = {}
    for t in m.trials.values():
        statuses[t.get("status") or "UNKNOWN"] = statuses.get(t.get("status") or "UNKNOWN", 0) + 1
    all_crit = [c for cs in m.criteria.values() for c in cs]
    return {"trials": len(m.trials), "patients": len(m.patients), "criteria": len(all_crit),
            "trial_status": statuses, "parser": parse_stats(all_crit),
            "dense_index": m.index is not None and m.index.emb is not None,
            "embedding_model": m.index.model if m.index else None}


@app.get("/api/trials")
def list_trials(q: str | None = None, limit: int = 25, offset: int = 0):
    m = get_matcher()
    if q:
        ids = [h[0] for h in m.index.search(q, k=offset + limit, mode="bm25")][offset:]
    else:
        ids = sorted(m.trials)[offset:offset + limit]
    return {"total": len(m.trials), "results": [m.trial_card(i) for i in ids]}


@app.get("/api/trials/{trial_id}")
def get_trial(trial_id: str):
    m = get_matcher()
    if trial_id not in m.trials:
        raise HTTPException(404, "trial not found")
    crit = m.criteria.get(trial_id, [])
    return {**m.trials[trial_id], "criteria": crit, "parse_stats": parse_stats(crit)}


@app.get("/api/patients")
def list_patients(limit: int = 500, condition: str | None = None):
    m = get_matcher()
    rows = [_patient_brief(r) for r in m.patients.values()]
    if condition:
        rows = [r for r in rows if any(condition.lower() in c.lower() for c in r["conditions"])]
    rows.sort(key=lambda r: (-len(r["conditions"]), r["name"]))
    return {"total": len(m.patients), "results": rows[:limit]}


@app.get("/api/patients/{patient_id}")
def get_patient(patient_id: str):
    m = get_matcher()
    if patient_id not in m.patients:
        raise HTTPException(404, "patient not found")
    return m.patients[patient_id]


class ManualProfile(BaseModel):
    age: float | None = None
    sex: str | None = None
    conditions: list[str] = []          # concept keys
    medications: list[str] = []         # concept keys
    labs: dict[str, float] = {}         # lab key -> value


class MatchRequest(BaseModel):
    patient_id: str | None = None
    text: str | None = None
    profile: ManualProfile | None = None
    k: int = 20
    mode: str = "hybrid"
    recruiting_only: bool = False


@app.post("/api/match/patient")
def match_patient(req: MatchRequest):
    m = get_matcher()
    if req.patient_id:
        if req.patient_id not in m.patients:
            raise HTTPException(404, "patient not found")
        profile = m.patients[req.patient_id]["profile"]
    elif req.text:
        profile = from_text(req.text)
    elif req.profile:
        mp = req.profile
        profile = {"patient_id": "manual", "name": "Manual profile", "age": mp.age, "sex": mp.sex,
                   "conditions": [{"concept": c, "display": CONCEPT_BY_KEY[c].label, "active": True} for c in mp.conditions
                                  if c in CONCEPT_BY_KEY],
                   "medications": [{"concept": c, "display": CONCEPT_BY_KEY[c].label, "active": True} for c in mp.medications
                                   if c in CONCEPT_BY_KEY],
                   "labs": {k: {"value": v, "unit": LAB_BY_KEY[k].unit, "date": None} for k, v in mp.labs.items() if k in LAB_BY_KEY},
                   "negated": [], "closed_world": True}
        profile["summary"] = summarise(profile)
    else:
        raise HTTPException(400, "give patient_id, text or profile")
    res = m.match_patient(profile, k=req.k, mode=req.mode, recruiting_only=req.recruiting_only)
    return {"profile": profile, **res}


@app.get("/api/match/trial/{trial_id}")
def match_trial(trial_id: str, k: int = 50):
    m = get_matcher()
    if trial_id not in m.trials:
        raise HTTPException(404, "trial not found")
    return m.match_trial(trial_id, k=k)


class ParseRequest(BaseModel):
    text: str


@app.post("/api/parse")
def parse(req: ParseRequest):
    crit = parse_eligibility(req.text)
    return {"criteria": crit, "stats": parse_stats(crit)}


@app.get("/api/vocab")
def vocab():
    from trialbridge.vocab import CONDITIONS, MEDICATIONS

    return {"conditions": [{"key": c.key, "label": c.label} for c in CONDITIONS],
            "medications": [{"key": c.key, "label": c.label} for c in MEDICATIONS],
            "labs": [{"key": l.key, "label": l.label, "unit": l.unit} for l in LABS]}


@app.get("/api/eval")
def evaluation():
    out = {}
    for f in sorted(config.RESULTS_DIR.glob("*.json")):
        out[f.stem] = json.loads(f.read_text())
    return out


# serve the built React app if present (single-process deployment)
_DIST = config.REPO_ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = _DIST / path
        return FileResponse(f if path and f.is_file() else _DIST / "index.html")
