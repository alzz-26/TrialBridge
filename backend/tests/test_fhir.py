from datetime import date

from trialbridge.patients.profile import from_fhir_bundle


def bundle():
    def e(r):
        return {"resource": r}

    return {"entry": [
        e({"resourceType": "Patient", "id": "p1", "gender": "female", "birthDate": "1970-06-01",
           "name": [{"given": ["Asha123"], "family": "Rao456"}]}),
        e({"resourceType": "Condition", "code": {"coding": [{"display": "Diabetes mellitus type 2 (disorder)"}]},
           "clinicalStatus": {"coding": [{"code": "active"}]}, "onsetDateTime": "2012-03-04T10:00:00Z"}),
        e({"resourceType": "Condition", "code": {"coding": [{"display": "Full-time employment (finding)"}]},
           "clinicalStatus": {"coding": [{"code": "active"}]}}),
        e({"resourceType": "Condition", "code": {"coding": [{"display": "Acute bronchitis (disorder)"}]},
           "clinicalStatus": {"coding": [{"code": "resolved"}]}, "onsetDateTime": "2020-01-01",
           "abatementDateTime": "2020-01-20"}),
        e({"resourceType": "Observation", "code": {"coding": [{"code": "4548-4"}]}, "effectiveDateTime": "2023-01-01",
           "valueQuantity": {"value": 7.1, "unit": "%"}}),
        e({"resourceType": "Observation", "code": {"coding": [{"code": "4548-4"}]}, "effectiveDateTime": "2024-01-01",
           "valueQuantity": {"value": 8.3, "unit": "%"}}),
        e({"resourceType": "Observation", "code": {"coding": [{"code": "85354-9"}]}, "effectiveDateTime": "2024-01-01",
           "component": [{"code": {"coding": [{"code": "8480-6"}]}, "valueQuantity": {"value": 141, "unit": "mm[Hg]"}},
                         {"code": {"coding": [{"code": "8462-4"}]}, "valueQuantity": {"value": 88, "unit": "mm[Hg]"}}]}),
        e({"resourceType": "MedicationRequest", "status": "active", "authoredOn": "2013-01-01",
           "medicationCodeableConcept": {"coding": [{"display": "24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet"}]}}),
    ]}


def test_fhir_profile():
    p = from_fhir_bundle(bundle(), ref_date=date(2025, 6, 1))
    assert p["name"] == "Asha Rao" and p["sex"] == "FEMALE" and p["age"] == 55.0
    concepts = {c["concept"] for c in p["conditions"]}
    assert "type2_diabetes" in concepts
    assert not any("employment" in c["display"].lower() for c in p["conditions"])  # social findings dropped
    assert p["labs"]["hba1c"]["value"] == 8.3  # latest value wins
    assert p["labs"]["sbp"]["value"] == 141 and p["labs"]["dbp"]["value"] == 88  # BP panel components
    assert p["medications"][0]["concept"] == "metformin" and p["medications"][0]["active"]
    assert "Diabetes mellitus type 2" in p["summary"]
