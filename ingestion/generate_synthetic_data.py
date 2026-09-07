"""
Phase 1 of the roadmap: synthetic data, so nothing here ever touches real PHI.

Writes one FHIR Bundle (JSON) per patient into data/synthetic_fhir/, in the same
shape a hospital's FHIR API would actually return. Patients are hand-designed
(not randomized) so the cohort demo later has a predictable, explainable answer.
"""
import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic_fhir"

ICD10 = "http://hl7.org/fhir/sid/icd-10"
SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"

T2D_CODING = [
    {"system": ICD10, "code": "E11.9", "display": "Type 2 diabetes mellitus without complications"},
    {"system": SNOMED, "code": "44054006", "display": "Type 2 diabetes mellitus"},
]
ESRD_CODING = [{"system": SNOMED, "code": "431857002", "display": "End stage renal disease"}]
PREGNANCY_CODING = [{"system": SNOMED, "code": "77386006", "display": "Pregnant"}]
HBA1C_CODING = [{"system": LOINC, "code": "4548-4", "display": "Hemoglobin A1c/Hemoglobin.total in Blood"}]
METFORMIN_CODING = [{"system": RXNORM, "code": "6809", "display": "Metformin"}]

# An intentionally "unrecognized" coding system/code, to demonstrate the
# vocabulary-mapping failure path (Chapter 03, concern #2) instead of hiding it.
UNMAPPED_CODING = [{"system": "http://example-hospital-local-codes.org", "code": "LOCALDX-991",
                     "display": "Diabetes (site-specific local code)"}]


def patient_resource(pid, gender, birth_date):
    return {
        "resourceType": "Patient",
        "id": pid,
        "identifier": [{"system": "urn:hospital-mrn", "value": f"MRN-{pid[-5:]}"}],
        "gender": gender,
        "birthDate": birth_date,
    }


def condition_resource(cid, pid, coding, onset_date):
    return {
        "resourceType": "Condition",
        "id": cid,
        "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": coding},
        "onsetDateTime": onset_date,
        "recordedDate": onset_date,
    }


def observation_resource(oid, pid, coding, effective_date, value, unit):
    return {
        "resourceType": "Observation",
        "id": oid,
        "subject": {"reference": f"Patient/{pid}"},
        "code": {"coding": coding},
        "effectiveDateTime": effective_date,
        "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": unit},
    }


def medication_resource(mid, pid, coding, start_date, status="active"):
    return {
        "resourceType": "MedicationStatement",
        "id": mid,
        "subject": {"reference": f"Patient/{pid}"},
        "medicationCodeableConcept": {"coding": coding},
        "status": status,
        "effectivePeriod": {"start": start_date},
    }


def bundle(resources):
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [{"resource": r} for r in resources],
    }


# Each patient: (id, gender, birth_date, [conditions], [observations], [medications])
# Designed so the demo cohort ("age>=40, T2D, HbA1c>7, on Metformin, no ESRD/pregnancy")
# has a clear, explainable answer: patients 01, 02, 08, 10, 11 should qualify.
PATIENTS = [
    dict(pid="fhir-synth-88213", gender="male", birth="1971-03-14",
         conditions=[("cond-1", T2D_CODING, "2022-06-01")],
         obs=[("obs-1", HBA1C_CODING, "2026-05-12", 8.2, "%")],
         meds=[("med-1", METFORMIN_CODING, "2022-06-10")]),  # 01 - the worked example -> INCLUDE

    dict(pid="fhir-synth-10042", gender="female", birth="1980-11-02",
         conditions=[("cond-2", T2D_CODING, "2023-01-15")],
         obs=[("obs-2", HBA1C_CODING, "2026-04-01", 9.1, "%")],
         meds=[("med-2", METFORMIN_CODING, "2023-02-01")]),  # 02 -> INCLUDE

    dict(pid="fhir-synth-10043", gender="male", birth="1988-07-22",
         conditions=[("cond-3", T2D_CODING, "2024-03-01")],
         obs=[("obs-3", HBA1C_CODING, "2026-03-11", 8.5, "%")],
         meds=[("med-3", METFORMIN_CODING, "2024-03-05")]),  # 03 -> EXCLUDE (age < 40)

    dict(pid="fhir-synth-10044", gender="female", birth="1965-02-19",
         conditions=[("cond-4", T2D_CODING, "2018-05-10")],
         obs=[("obs-4", HBA1C_CODING, "2026-02-20", 6.5, "%")],
         meds=[("med-4", METFORMIN_CODING, "2018-06-01")]),  # 04 -> EXCLUDE (HbA1c not > 7)

    dict(pid="fhir-synth-10045", gender="male", birth="1975-09-30",
         conditions=[("cond-5", T2D_CODING, "2021-01-01")],
         obs=[("obs-5", HBA1C_CODING, "2026-05-01", 7.8, "%")],
         meds=[]),  # 05 -> EXCLUDE (no Metformin exposure)

    dict(pid="fhir-synth-10046", gender="female", birth="1960-12-05",
         conditions=[("cond-6a", T2D_CODING, "2015-04-01"), ("cond-6b", ESRD_CODING, "2024-01-01")],
         obs=[("obs-6", HBA1C_CODING, "2026-04-15", 8.0, "%")],
         meds=[("med-6", METFORMIN_CODING, "2015-05-01")]),  # 06 -> EXCLUDE (severe renal disease)

    dict(pid="fhir-synth-10047", gender="male", birth="1994-06-18",
         conditions=[],
         obs=[],
         meds=[]),  # 07 -> EXCLUDE (no T2D at all — routine checkup patient)

    dict(pid="fhir-synth-10048", gender="female", birth="1983-01-25",
         conditions=[("cond-8", T2D_CODING, "2020-08-01")],
         obs=[("obs-8", HBA1C_CODING, "2026-05-20", 7.5, "%")],
         meds=[("med-8", METFORMIN_CODING, "2020-08-15")]),  # 08 -> INCLUDE

    dict(pid="fhir-synth-10049", gender="female", birth="1955-03-03",
         conditions=[("cond-9a", T2D_CODING, "2010-01-01"), ("cond-9b", PREGNANCY_CODING, "2026-01-01")],
         obs=[("obs-9", HBA1C_CODING, "2026-05-02", 9.9, "%")],
         meds=[("med-9", METFORMIN_CODING, "2010-02-01")]),  # 09 -> EXCLUDE (pregnancy)

    dict(pid="fhir-synth-10050", gender="male", birth="1977-10-11",
         conditions=[("cond-10", T2D_CODING, "2025-12-01")],
         obs=[("obs-10", HBA1C_CODING, "2026-05-18", 8.8, "%")],
         meds=[("med-10", METFORMIN_CODING, "2026-03-01")]),  # 10 -> INCLUDE (recent Metformin start)

    dict(pid="fhir-synth-10051", gender="female", birth="1973-04-28",
         conditions=[("cond-11", T2D_CODING, "2019-07-01")],
         obs=[("obs-11", HBA1C_CODING, "2026-04-28", 7.1, "%")],
         meds=[("med-11", METFORMIN_CODING, "2019-07-20")]),  # 11 -> INCLUDE (just above threshold)

    dict(pid="fhir-synth-10052", gender="male", birth="1968-08-14",
         conditions=[("cond-12", T2D_CODING, "2016-03-01")],
         obs=[],  # no HbA1c ever recorded
         meds=[("med-12", METFORMIN_CODING, "2016-03-15")]),  # 12 -> EXCLUDE (missing measurement)

    dict(pid="fhir-synth-10053", gender="female", birth="1969-05-09",
         conditions=[("cond-13", UNMAPPED_CODING, "2022-01-01")],  # deliberately unmappable code
         obs=[("obs-13", HBA1C_CODING, "2026-05-05", 8.9, "%")],
         meds=[("med-13", METFORMIN_CODING, "2022-01-10")]),  # 13 -> demonstrates the unmapped-code path
]


def build_bundle(p):
    resources = [patient_resource(p["pid"], p["gender"], p["birth"])]
    for cid, coding, onset in p["conditions"]:
        resources.append(condition_resource(cid, p["pid"], coding, onset))
    for oid, coding, eff, value, unit in p["obs"]:
        resources.append(observation_resource(oid, p["pid"], coding, eff, value, unit))
    for mid, coding, start in p["meds"]:
        resources.append(medication_resource(mid, p["pid"], coding, start))
    return bundle(resources)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for p in PATIENTS:
        out_file = OUT_DIR / f"{p['pid']}.json"
        out_file.write_text(json.dumps(build_bundle(p), indent=2), encoding="utf-8")
    print(f"Wrote {len(PATIENTS)} synthetic FHIR bundles to {OUT_DIR}")


if __name__ == "__main__":
    main()
