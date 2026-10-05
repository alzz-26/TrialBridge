from pathlib import Path

from trialbridge.criteria.parser import is_negated, parse_criterion, parse_eligibility, split_items, split_sections

SAMPLE = (Path(__file__).parent / "sample_criteria.txt").read_text(encoding="utf-8")


def preds(text, kind="inclusion"):
    return parse_criterion(text, kind)["predicates"]


def test_sections_and_items():
    secs = split_sections(SAMPLE)
    assert [k for k, _ in secs] == ["inclusion", "exclusion"]
    exc = split_items(secs[1][1])
    # sub-bullets inherit their lead-in text
    assert any(i.startswith("Any of the following: Hemoglobin") for i in exc)
    assert len(split_items(secs[0][1])) == 5


def test_lab_thresholds():
    assert preds("eGFR > 45 mL/min/1.73m2")[0].items() >= {"lab": "egfr", "op": ">", "value": 45.0}.items()
    assert preds("HbA1c between 7.0% and 10.5%")[0]["value"] == [7.0, 10.5]
    assert preds("HbA1c 7.0-10.0%")[0]["value"] == [7.0, 10.0]
    assert preds("BMI ≥ 25 kg/m2")[0]["op"] == ">="
    assert preds("Platelets < 100,000/mm3")[0]["value"] == 100.0  # thousands -> x10^3/uL
    assert preds("Hemoglobin < 100 g/L")[0]["value"] == 10.0  # g/L -> g/dL


def test_uln_multiplier():
    p = preds("ALT or AST > 3 x ULN", "exclusion")
    assert {x["lab"] for x in p} == {"alt", "ast"}
    assert all(x["value"] == 120 for x in p)


def test_age_text():
    assert {k: v for k, v in preds("Aged 18 to 65 years")[0].items() if k != "span"} == {"type": "age", "op": "between", "value": [18, 65]}
    assert preds("Patients 50 years or older")[0]["op"] == ">="


def test_temporal_and_concepts():
    p = preds("History of myocardial infarction or stroke within 6 months", "exclusion")
    keys = {x["concept"] for x in p}
    assert {"myocardial_infarction", "stroke"} <= keys
    assert all(x["within_days"] == 183 for x in p)


def test_negation():
    p = preds("No history of heart failure")
    assert p[0]["concept"] == "heart_failure" and p[0]["negated"] is True
    assert not is_negated("Diagnosed with heart failure", 15)


def test_type_disambiguation():
    assert {x["concept"] for x in preds("Type 1 diabetes")} == {"type1_diabetes"}
    assert {x["concept"] for x in preds("Prediabetes")} == {"prediabetes"}


def test_unparsed_residue():
    assert preds("Any condition that in the opinion of the investigator would interfere")[0]["type"] == "unparsed"


def test_structured_fields():
    crit = parse_eligibility(SAMPLE, 18, 75, "FEMALE")
    assert crit[0]["predicates"][0] == {"type": "age", "op": "between", "value": [18, 75]}
    assert crit[1]["predicates"][0] == {"type": "sex", "value": "FEMALE"}


def test_inline_header_content_is_kept():
    crit = parse_eligibility("Inclusion Criteria: 18 years, intention to breastfeed, single gestation\n\n"
                             "Exclusion Criteria: Twin gestation")
    texts = [c["text"] for c in crit]
    assert any("intention to breastfeed" in t for t in texts)
    assert any(t.startswith("Twin gestation") for t in texts)


def test_partial_parse_is_flagged():
    p = preds("Patients aged 12-80 eligible to receive bone marrow for allogeneic transplantation as determined by physician")
    assert any(x.get("partial") for x in p)
    assert not any(x.get("partial") for x in preds("eGFR > 45 mL/min/1.73m2"))
