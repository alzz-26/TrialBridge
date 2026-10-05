"""Patient representation.

A PatientProfile is a plain dict so it serialises straight to JSON / the API:

{
  "patient_id": "...", "name": "...", "sex": "MALE"|"FEMALE"|None, "age": 54.2,
  "conditions":  [{"concept": "type2_diabetes", "display": "...", "onset": "2015-04-02",
                   "active": true}],
  "medications": [{"concept": "metformin", "display": "...", "start": "...", "active": true}],
  "labs": {"hba1c": {"value": 8.1, "unit": "%", "date": "2024-01-03"}},
  "negated": ["myocardial_infarction"],   # explicitly ruled out (free-text input)
  "closed_world": true,                   # absent condition == does not have it
  "summary": "54-year-old male with type 2 diabetes, hypertension ..."
}

Two builders: Synthea FHIR bundles (structured EHR) and free-text descriptions
(TREC topics, or a patient typing their own history).
"""

import json
import re
from datetime import date, datetime
from pathlib import Path

from trialbridge.criteria.parser import is_negated
from trialbridge.vocab import CONDITIONS, LAB_BY_KEY, LABS, LOINC_TO_LAB, MEDICATIONS, PARENTS, classify_display, find_concepts


def _d(s: str | None) -> str | None:
    return s[:10] if s else None


def _age(birth: str, ref: date | None = None) -> float:
    b = datetime.strptime(birth[:10], "%Y-%m-%d").date()
    ref = ref or date.today()
    return round((ref - b).days / 365.25, 1)


def summarise(p: dict) -> str:
    bits = []
    if p.get("age") is not None:
        bits.append(f"{p['age']:.0f}-year-old")
    bits.append({"MALE": "male", "FEMALE": "female"}.get(p.get("sex") or "", "patient"))
    conds = sorted({c["display"] for c in p["conditions"] if c.get("active", True)})
    if conds:
        bits.append("with " + ", ".join(conds[:15]))
    meds = sorted({m["display"] for m in p["medications"] if m.get("active", True)})
    if meds:
        bits.append("taking " + ", ".join(meds[:8]))
    labs = [f"{LAB_BY_KEY[k].label} {v['value']:g}" for k, v in p["labs"].items()]
    if labs:
        bits.append("labs: " + ", ".join(labs))
    return " ".join(bits)


# ----------------------------------------------------------------------------- Synthea / FHIR
_SYNTHEA_NOISE = re.compile(r"\((?:finding|disorder|situation|procedure|morphologic abnormality|person)\)", re.I)
_SOCIAL = re.compile(r"(?:employment|education|received higher|housing|stress|social isolation|limited social|"
                     r"medication review due|risk activity|criminal record|reports of violence|lack of access|"
                     r"has a criminal|victim of|unemployed|part-time|not in labor force)", re.I)


def from_fhir_bundle(bundle: dict, ref_date: date | None = None) -> dict:
    res = [e["resource"] for e in bundle.get("entry", []) if "resource" in e]
    patient = next(r for r in res if r["resourceType"] == "Patient")
    name = patient.get("name", [{}])[0]
    full_name = " ".join(name.get("given", []) + [name.get("family", "")]).strip()
    full_name = re.sub(r"\d+", "", full_name)  # Synthea appends digits to names
    deceased = patient.get("deceasedDateTime")
    ref = ref_date or (datetime.strptime(deceased[:10], "%Y-%m-%d").date() if deceased else date.today())

    conditions = []
    for r in res:
        if r["resourceType"] != "Condition":
            continue
        disp = (r.get("code", {}).get("coding") or [{}])[0].get("display") or r.get("code", {}).get("text", "")
        if _SOCIAL.search(disp):
            continue
        status = ((r.get("clinicalStatus") or {}).get("coding") or [{}])[0].get("code", "active")
        concepts = classify_display(disp, CONDITIONS)
        clean = _SYNTHEA_NOISE.sub("", disp).strip()
        for c in concepts or [None]:
            conditions.append({"concept": c, "display": clean, "onset": _d(r.get("onsetDateTime")),
                               "abatement": _d(r.get("abatementDateTime")),
                               "active": status == "active" and not r.get("abatementDateTime")})

    meds = []
    for r in res:
        if r["resourceType"] != "MedicationRequest":
            continue
        disp = (r.get("medicationCodeableConcept", {}).get("coding") or [{}])[0].get("display", "")
        concepts = classify_display(disp, MEDICATIONS)
        for c in concepts or [None]:
            meds.append({"concept": c, "display": disp, "start": _d(r.get("authoredOn")),
                         "active": r.get("status") == "active"})

    labs: dict[str, dict] = {}

    def add_lab(code: str, q: dict, when: str | None):
        key = LOINC_TO_LAB.get(code)
        if not key or q.get("value") is None:
            return
        if key not in labs or (when or "") >= (labs[key]["date"] or ""):
            labs[key] = {"value": round(float(q["value"]), 2), "unit": q.get("unit"), "date": _d(when)}

    for r in res:
        if r["resourceType"] != "Observation":
            continue
        when = r.get("effectiveDateTime")
        for coding in r.get("code", {}).get("coding", []):
            if "valueQuantity" in r:
                add_lab(coding.get("code"), r["valueQuantity"], when)
        for comp in r.get("component", []) or []:
            for coding in comp.get("code", {}).get("coding", []):
                if "valueQuantity" in comp:
                    add_lab(coding.get("code"), comp["valueQuantity"], when)

    # Synthea reports eGFR > 60 as a plain number; platelet counts in 10*3/uL already.
    p = {
        "patient_id": patient["id"], "name": full_name,
        "sex": {"male": "MALE", "female": "FEMALE"}.get(patient.get("gender")),
        "birth_date": patient.get("birthDate"), "age": _age(patient["birthDate"], ref),
        "deceased": bool(deceased), "conditions": conditions, "medications": meds, "labs": labs,
        "negated": [], "closed_world": True, "reference_date": ref.isoformat(),
    }
    p["summary"] = summarise(p)
    return p


def load_synthea_dir(path: Path, limit: int | None = None) -> list[dict]:
    files = sorted(f for f in path.glob("*.json") if not f.name.startswith(("hospital", "practitioner")))
    out = []
    for f in files[:limit]:
        with open(f, encoding="utf-8") as fh:
            out.append(from_fhir_bundle(json.load(fh)))
    return out


# ----------------------------------------------------------------------------- free text
_AGE_TXT = re.compile(r"(\d{1,3})[- ](?:year|yr)s?[- ]old|\b(\d{1,3})\s?(?:yo|y/o|y\.o\.)\b|\baged? (\d{1,3})\b", re.I)
_MALE = re.compile(r"\b(?:man|male|boy|gentleman|he|his|him|mr)\b", re.I)
_FEMALE = re.compile(r"\b(?:woman|female|girl|lady|she|her|hers|mrs|ms)\b", re.I)
_VALUE = re.compile(r"(?:\s*(?:of|is|was|=|:|at|level(?: of)?|measured at|value of))?\s*(\d+(?:\.\d+)?)", re.I)


def from_text(text: str, patient_id: str = "free-text", name: str = "Free-text patient") -> dict:
    age = None
    m = _AGE_TXT.search(text)
    if m:
        age = float(next(g for g in m.groups() if g))
    n_m, n_f = len(_MALE.findall(text)), len(_FEMALE.findall(text))
    sex = "MALE" if n_m > n_f else "FEMALE" if n_f > n_m else None

    conditions, negated = [], []
    for concept, cm in find_concepts(text, CONDITIONS):
        if is_negated(text, cm.start()):
            negated.append(concept.key)
            continue
        for k in [concept.key] + PARENTS.get(concept.key, []):
            conditions.append({"concept": k, "display": cm.group(0), "onset": None, "active": True})
    meds = []
    for concept, mm in find_concepts(text, MEDICATIONS):
        if not is_negated(text, mm.start()):
            meds.append({"concept": concept.key, "display": mm.group(0), "start": None, "active": True})
    labs = {}
    for lab in LABS:
        for lm in lab._rx.finditer(text):
            v = _VALUE.match(text, lm.end())
            if v:
                labs[lab.key] = {"value": float(v.group(1)), "unit": lab.unit, "date": None}
                break

    p = {"patient_id": patient_id, "name": name, "sex": sex, "age": age, "conditions": conditions,
         "medications": meds, "labs": labs, "negated": sorted(set(negated)), "closed_world": False,
         "source_text": text}
    p["summary"] = text.strip()[:2000]
    return p
