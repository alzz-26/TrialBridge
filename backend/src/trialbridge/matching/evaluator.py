"""Deterministic predicate evaluator with three-valued (Kleene) logic.

Every predicate evaluates to True / False / None (unknown). Criteria combine
predicates, trials combine criteria. Every decision carries a human-readable
reason so a clinician can audit *why* a patient was matched or rejected.

Inclusion criterion  -> met | not_met | unknown
Exclusion criterion  -> clear (patient is not excluded) | excluded | unknown
Trial                -> eligible | possibly_eligible | ineligible
"""

import re
from datetime import date, datetime

from trialbridge.vocab import CONCEPT_BY_KEY, LAB_BY_KEY

T, F, U = True, False, None


def k_and(vals):
    vals = list(vals)
    if any(v is F for v in vals):
        return F
    return U if any(v is U for v in vals) else T


def k_or(vals):
    vals = list(vals)
    if any(v is T for v in vals):
        return T
    return U if any(v is U for v in vals) else F


def k_not(v):
    return U if v is U else not v


def _cmp(x: float, op: str, v) -> bool:
    if op == "between":
        return v[0] <= x <= v[1]
    return {">=": x >= v, ">": x > v, "<=": x <= v, "<": x < v, "=": abs(x - v) < 1e-9}[op]


def _fmt(op: str, v) -> str:
    return f"{v[0]:g}–{v[1]:g}" if op == "between" else f"{ {'>=': '≥', '<=': '≤'}.get(op, op)} {v:g}"


def _ref_date(p: dict) -> date:
    r = p.get("reference_date")
    return datetime.strptime(r, "%Y-%m-%d").date() if r else date.today()


def _days_since(d: str | None, ref: date) -> int | None:
    if not d:
        return None
    return (ref - datetime.strptime(d[:10], "%Y-%m-%d").date()).days


# ----------------------------------------------------------------------------- predicates
def eval_predicate(pred: dict, p: dict) -> tuple[bool | None, str]:
    t = pred["type"]
    if t == "age":
        if p.get("age") is None:
            return U, "age not recorded"
        ok = _cmp(p["age"], pred["op"], pred["value"])
        return ok, f"age {p['age']:g} {'satisfies' if ok else 'fails'} {_fmt(pred['op'], pred['value'])}"
    if t == "sex":
        if not p.get("sex"):
            return U, "sex not recorded"
        ok = p["sex"] == pred["value"]
        return ok, f"sex {p['sex'].lower()} {'matches' if ok else 'does not match'} {pred['value'].lower()}"
    if t == "lab":
        lab = LAB_BY_KEY[pred["lab"]]
        obs = p.get("labs", {}).get(pred["lab"])
        if not obs:
            return U, f"no {lab.label} result on record"
        ok = _cmp(obs["value"], pred["op"], pred["value"])
        when = f" ({obs['date']})" if obs.get("date") else ""
        return ok, f"{lab.label} {obs['value']:g}{when} {'satisfies' if ok else 'fails'} {_fmt(pred['op'], pred['value'])} {lab.unit}"
    if t in ("condition", "medication"):
        return _eval_concept(pred, p, "conditions" if t == "condition" else "medications")
    if pred.get("partial"):
        return U, f"unparsed remainder ({' '.join(pred.get('residual', [])[:6])}…) needs LLM review"
    return U, "criterion not machine-readable yet (LLM residue)"


def _eval_concept(pred: dict, p: dict, field: str) -> tuple[bool | None, str]:
    key = pred["concept"]
    label = CONCEPT_BY_KEY[key].label if key in CONCEPT_BY_KEY else key
    ref = _ref_date(p)
    hits = [c for c in p.get(field, []) if c.get("concept") == key]
    window = pred.get("within_days")
    concept = CONCEPT_BY_KEY.get(key)
    acute_only = concept is not None and concept.acute and pred.get("status") != "ever" and not pred.get("within_days")
    if (pred.get("status") == "active" or acute_only) and field == "conditions":
        hits = [c for c in hits if c.get("active", True)]
    if window:
        recent = []
        for c in hits:
            ds = _days_since(c.get("onset") or c.get("start"), ref)
            if ds is None:
                recent.append(c) if c.get("active") else None
            elif ds <= window or (c.get("active") and field == "medications"):
                recent.append(c)
        hits = recent
    if hits:
        h = hits[0]
        when = f", since {h.get('onset') or h.get('start')}" if (h.get("onset") or h.get("start")) else ""
        scope = f" within {window} days" if window else ""
        return T, f"record shows '{h['display']}'{when}{scope}"
    if key in p.get("negated", []):
        return F, f"{label} explicitly ruled out"
    if p.get("closed_world", False):
        scope = f" in the last {window} days" if window else ""
        return F, f"no {label.lower()} on record{scope}"
    return U, f"{label.lower()} not mentioned"


# ----------------------------------------------------------------------------- criteria
def _qualifier(text: str, a: list[int], b: list[int]) -> bool:
    """Is span b (a lab) a qualifier of span a (a condition), e.g. 'hypertension (SBP > 160)'?"""
    lo, hi = sorted([a[1], b[0]]) if a[1] <= b[0] else (b[1], a[0])
    between = text[lo:hi]
    return bool(re.search(r"\(|defined as|with|:|i\.e\.|as evidenced|requiring", between, re.I)) and len(between) < 40


def eval_criterion(c: dict, p: dict) -> dict:
    preds = [x for x in c["predicates"] if x["type"] != "covered"]
    if not preds:
        return {**c, "status": "covered", "reasons": ["covered by registry age field"]}
    results = [(x, *eval_predicate(x, p)) for x in preds]
    reasons = [r for _, _, r in results]

    def group(types, negated=None):
        return [v for x, v, _ in results if x["type"] in types and (negated is None or x.get("negated", False) == negated)]

    if all(x["type"] == "unparsed" for x in preds):
        status = "unknown"
    elif c["kind"] == "inclusion":
        parts = []
        parts += group({"age", "sex", "lab"})
        pos_c, neg_c = group({"condition"}, False), group({"condition"}, True)
        pos_m, neg_m = group({"medication"}, False), group({"medication"}, True)
        if pos_c:
            parts.append(k_or(pos_c))
        if pos_m:
            parts.append(k_or(pos_m))
        parts += [k_not(v) for v in neg_c + neg_m]
        parts += group({"unparsed"})  # partially parsed: a definite failure still fails, otherwise unknown
        v = k_and(parts)
        status = {T: "met", F: "not_met", U: "unknown"}[v]
    else:  # exclusion: triggered if any positive mention is true
        conds = [(x, v) for x, v, _ in results if x["type"] in ("condition", "medication")]
        labs = [(x, v) for x, v, _ in results if x["type"] in ("lab", "age", "sex")]
        qualified = conds and labs and any(_qualifier(c["text"], cx.get("span", [0, 0]), lx.get("span", [0, 0]))
                                           for cx, _ in conds for lx, _ in labs if "span" in cx and "span" in lx)
        cond_vals = [k_not(v) if x.get("negated") else v for x, v in conds]
        lab_vals = [v for _, v in labs]
        if qualified:
            trig = k_and([k_or(cond_vals), k_or(lab_vals)])
        else:
            trig = k_or(cond_vals + lab_vals)
        trig = k_or([trig] + group({"unparsed"}))  # partially parsed: a definite hit still excludes
        status = {T: "excluded", F: "clear", U: "unknown"}[trig]
    return {**c, "status": status, "reasons": reasons}


def eval_trial(criteria: list[dict], p: dict) -> dict:
    evaluated = [eval_criterion(c, p) for c in criteria]
    scored = [e for e in evaluated if e["status"] != "covered"]
    passed = sum(e["status"] in ("met", "clear") for e in scored)
    failed = [e for e in scored if e["status"] in ("not_met", "excluded")]
    unknown = sum(e["status"] == "unknown" for e in scored)
    n = len(scored) or 1
    if failed:
        verdict = "ineligible"
    elif unknown:
        verdict = "possibly_eligible"
    else:
        verdict = "eligible"
    # eligibility score in [0, 1]: passes count fully, unknowns half; any hard fail caps the score
    score = (passed + 0.5 * unknown) / n
    if failed:
        score *= 0.25 / len(failed)
    return {"verdict": verdict, "score": round(score, 4), "passed": passed, "failed": len(failed),
            "unknown": unknown, "total": len(scored), "criteria": evaluated}
