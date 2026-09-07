"""
Task 1b: the actual "JSON -> OMOP" mapping, merged into the exact same
omop.person / condition_occurrence / measurement / drug_exposure tables that
Task 1a's SynPUF bulk-load already populated — this is where the mechanics
SynPUF skipped (it arrived pre-mapped) actually happen: reading the Iceberg
raw layer, resolving each source code through the vocabulary, and assigning
new surrogate keys that can't collide with SynPUF's existing ID ranges
(computed as max(existing_id)+1 per table, not a guessed offset).

omop._fhir_patient_map tracks which person_id came from this pipeline (vs.
SynPUF), and makes reruns idempotent: a patient already merged gets their
clinical rows replaced, not duplicated. This is the lineage piece from
Chapter 03 concern #1 made concrete — every row here is traceable back to an
exact FHIR patient id and Iceberg batch.
"""
import csv
import json
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from raw.iceberg_catalog import get_or_create_raw_table  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SCHEMA = "omop"
VOCAB_CSV = Path(__file__).resolve().parent.parent / "vocabulary" / "mini_concepts.csv"

MAP_TABLE_DDL = f"""
create table if not exists {SCHEMA}._fhir_patient_map (
    fhir_patient_id text primary key,
    person_id integer not null unique,
    source_batch_id text
);
"""


def get_conn():
    return psycopg2.connect(
        host=os.environ["PGHOST"], port=os.environ["PGPORT"],
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        dbname=os.environ["PGDATABASE"],
    )


def load_vocab():
    vocab = {}
    with open(VOCAB_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vocab[(row["source_system"], row["source_code"])] = int(row["standard_concept_id"])
    return vocab


def best_concept_id(codings, vocab):
    """Prefer a mapped coding if any of the resource's codings has one; else 0 (real OMOP's 'unmapped')."""
    for c in codings:
        cid = vocab.get((c.get("system"), c.get("code")))
        if cid is not None:
            return cid
    return 0


class IdAllocator:
    """max(existing_id)+1 per table, then increments in memory — no collisions with SynPUF's IDs."""
    def __init__(self, conn, table, id_col):
        with conn.cursor() as cur:
            cur.execute(f"select coalesce(max({id_col}), 0) from {SCHEMA}.{table}")
            self.next_id = cur.fetchone()[0] + 1

    def take(self):
        val = self.next_id
        self.next_id += 1
        return val


def main():
    vocab = load_vocab()
    raw_table = get_or_create_raw_table()
    rows = raw_table.scan().to_arrow().to_pylist()
    resources = [json.loads(r["raw_json"]) | {"_patient_id": r["patient_id"],
                                               "_resource_type": r["resource_type"],
                                               "_batch_id": r["batch_id"]} for r in rows]

    patients = [r for r in resources if r["_resource_type"] == "Patient"]
    conditions = [r for r in resources if r["_resource_type"] == "Condition"]
    observations = [r for r in resources if r["_resource_type"] == "Observation"]
    meds = [r for r in resources if r["_resource_type"] == "MedicationStatement"]

    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(MAP_TABLE_DDL)
    conn.commit()

    person_alloc = IdAllocator(conn, "person", "person_id")
    cond_alloc = IdAllocator(conn, "condition_occurrence", "condition_occurrence_id")
    meas_alloc = IdAllocator(conn, "measurement", "measurement_id")
    drug_alloc = IdAllocator(conn, "drug_exposure", "drug_exposure_id")

    patient_id_map = {}  # fhir patient id -> person_id
    new_patients, reused_patients = 0, 0

    with conn.cursor() as cur:
        for p in patients:
            fhir_id = p["id"]
            cur.execute(f"select person_id from {SCHEMA}._fhir_patient_map where fhir_patient_id = %s", (fhir_id,))
            existing = cur.fetchone()
            if existing:
                person_id = existing[0]
                reused_patients += 1
                # idempotent rerun: wipe this person's previously-merged clinical rows first
                cur.execute(f"delete from {SCHEMA}.condition_occurrence where person_id = %s", (person_id,))
                cur.execute(f"delete from {SCHEMA}.measurement where person_id = %s", (person_id,))
                cur.execute(f"delete from {SCHEMA}.drug_exposure where person_id = %s", (person_id,))
            else:
                person_id = person_alloc.take()
                new_patients += 1
                gender_concept = 8507 if p.get("gender") == "male" else 8532 if p.get("gender") == "female" else 0
                birth_date = p.get("birthDate")
                year = int(birth_date[:4]) if birth_date else None
                cur.execute(
                    f"""insert into {SCHEMA}.person
                        (person_id, gender_concept_id, year_of_birth, birth_datetime,
                         race_concept_id, ethnicity_concept_id, person_source_value)
                        values (%s, %s, %s, %s, 0, 0, %s)""",
                    (person_id, gender_concept, year, birth_date, fhir_id),
                )
                cur.execute(
                    f"""insert into {SCHEMA}._fhir_patient_map (fhir_patient_id, person_id, source_batch_id)
                        values (%s, %s, %s)""",
                    (fhir_id, person_id, p["_batch_id"]),
                )
            patient_id_map[fhir_id] = person_id

        n_cond = n_meas = n_drug = 0
        for c in conditions:
            person_id = patient_id_map.get(c["_patient_id"])
            if person_id is None:
                continue
            concept_id = best_concept_id(c.get("code", {}).get("coding", []), vocab)
            source_code = (c.get("code", {}).get("coding") or [{}])[0].get("code")
            cur.execute(
                f"""insert into {SCHEMA}.condition_occurrence
                    (condition_occurrence_id, person_id, condition_concept_id,
                     condition_start_date, condition_type_concept_id, condition_source_value)
                    values (%s, %s, %s, %s, 0, %s)""",
                (cond_alloc.take(), person_id, concept_id, c.get("onsetDateTime"), source_code),
            )
            n_cond += 1

        for o in observations:
            person_id = patient_id_map.get(o["_patient_id"])
            if person_id is None:
                continue
            concept_id = best_concept_id(o.get("code", {}).get("coding", []), vocab)
            value = o.get("valueQuantity", {}).get("value")
            unit = o.get("valueQuantity", {}).get("unit")
            cur.execute(
                f"""insert into {SCHEMA}.measurement
                    (measurement_id, person_id, measurement_concept_id, measurement_date,
                     measurement_type_concept_id, value_as_number, unit_source_value)
                    values (%s, %s, %s, %s, 0, %s, %s)""",
                (meas_alloc.take(), person_id, concept_id, o.get("effectiveDateTime"), value, unit),
            )
            n_meas += 1

        for m in meds:
            person_id = patient_id_map.get(m["_patient_id"])
            if person_id is None:
                continue
            concept_id = best_concept_id(m.get("medicationCodeableConcept", {}).get("coding", []), vocab)
            start = m.get("effectivePeriod", {}).get("start")
            cur.execute(
                f"""insert into {SCHEMA}.drug_exposure
                    (drug_exposure_id, person_id, drug_concept_id, drug_exposure_start_date,
                     drug_exposure_end_date, drug_type_concept_id, drug_source_value)
                    values (%s, %s, %s, %s, %s, 0, %s)""",
                (drug_alloc.take(), person_id, concept_id, start, start, m.get("status")),
            )
            n_drug += 1

    with conn.cursor() as cur:
        cur.execute(f"select min(person_id), max(person_id), count(*) from {SCHEMA}._fhir_patient_map")
        min_id, max_id, total = cur.fetchone()
    conn.commit()
    conn.close()

    print(f"Patients: {new_patients} new, {reused_patients} reused (rerun-safe)")
    print(f"Inserted: {n_cond} conditions, {n_meas} measurements, {n_drug} drug exposures")
    print(f"FHIR-sourced patients in omop.person: {total} total, person_id {min_id}..{max_id}")


if __name__ == "__main__":
    main()
