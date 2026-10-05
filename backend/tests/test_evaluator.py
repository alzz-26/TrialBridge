from pathlib import Path

from trialbridge.criteria.parser import parse_eligibility
from trialbridge.matching.evaluator import U, eval_trial, k_and, k_not, k_or
from trialbridge.patients.profile import from_text

SAMPLE = (Path(__file__).parent / "sample_criteria.txt").read_text(encoding="utf-8")
CRITERIA = parse_eligibility(SAMPLE, 18, 75, "ALL")


def patient(**kw):
    p = {"patient_id": "t", "name": "t", "age": 58, "sex": "MALE", "reference_date": "2026-01-01",
         "conditions": [{"concept": "type2_diabetes", "display": "Diabetes mellitus type 2", "onset": "2015-01-01", "active": True}],
         "medications": [{"concept": "metformin", "display": "Metformin 500 MG", "start": "2016-01-01", "active": True}],
         "labs": {"hba1c": {"value": 8.2, "date": "2025-12-01"}, "egfr": {"value": 72, "date": "2025-12-01"},
                  "bmi": {"value": 31.0, "date": "2025-12-01"}, "hemoglobin": {"value": 14, "date": "2025-12-01"},
                  "platelets": {"value": 250, "date": "2025-12-01"}, "alt": {"value": 30, "date": "2025-12-01"},
                  "ast": {"value": 28, "date": "2025-12-01"}, "sbp": {"value": 132, "date": "2025-12-01"}},
         "negated": [], "closed_world": True}
    p.update(kw)
    return p


def by_text(res, fragment):
    return next(c for c in res["criteria"] if fragment in c["text"])


def test_kleene():
    assert k_and([True, U]) is U and k_and([False, U]) is False
    assert k_or([True, U]) is True and k_or([False, U]) is U
    assert k_not(U) is U


def test_ideal_patient_is_only_blocked_by_residue():
    res = eval_trial(CRITERIA, patient())
    assert res["verdict"] == "possibly_eligible"  # the "investigator opinion" criterion is unknown
    assert res["failed"] == 0 and res["unknown"] == 1


def test_lab_failure():
    p = patient()
    p["labs"]["egfr"] = {"value": 38, "date": "2025-12-01"}
    res = eval_trial(CRITERIA, p)
    assert res["verdict"] == "ineligible"
    assert by_text(res, "eGFR")["status"] == "not_met"


def test_recent_mi_excludes_but_old_mi_does_not():
    recent = patient(conditions=patient()["conditions"] + [
        {"concept": "myocardial_infarction", "display": "Myocardial infarction", "onset": "2025-10-01", "active": False}])
    old = patient(conditions=patient()["conditions"] + [
        {"concept": "myocardial_infarction", "display": "Myocardial infarction", "onset": "2019-10-01", "active": False}])
    assert by_text(eval_trial(CRITERIA, recent), "myocardial")["status"] == "excluded"
    assert by_text(eval_trial(CRITERIA, old), "myocardial")["status"] == "clear"


def test_controlled_hypertension_is_not_excluded():
    p = patient(conditions=patient()["conditions"] + [
        {"concept": "hypertension", "display": "Essential hypertension", "onset": "2010-01-01", "active": True}])
    assert by_text(eval_trial(CRITERIA, p), "Uncontrolled hypertension")["status"] == "clear"
    p["labs"]["sbp"] = {"value": 172, "date": "2025-12-01"}
    assert by_text(eval_trial(CRITERIA, p), "Uncontrolled hypertension")["status"] == "excluded"


def test_missing_lab_is_unknown_not_failure():
    p = patient()
    del p["labs"]["hba1c"]
    res = eval_trial(CRITERIA, p)
    assert by_text(res, "HbA1c")["status"] == "unknown"
    assert res["verdict"] == "possibly_eligible"


def test_free_text_patient():
    p = from_text("A 62-year-old man with type 2 diabetes on metformin. HbA1c of 8.4. No history of heart failure.")
    assert p["age"] == 62 and p["sex"] == "MALE"
    assert {c["concept"] for c in p["conditions"]} == {"type2_diabetes"}
    assert p["labs"]["hba1c"]["value"] == 8.4
    assert "heart_failure" in p["negated"]


def test_past_pregnancy_does_not_exclude():
    past = {"concept": "pregnancy", "display": "Normal pregnancy", "onset": "2001-01-01", "active": False}
    p = patient(sex="FEMALE", conditions=patient()["conditions"] + [past])
    assert by_text(eval_trial(CRITERIA, p), "Pregnant")["status"] == "clear"
    p["conditions"][-1] = {**past, "onset": "2025-11-01", "active": True}
    assert by_text(eval_trial(CRITERIA, p), "Pregnant")["status"] == "excluded"
