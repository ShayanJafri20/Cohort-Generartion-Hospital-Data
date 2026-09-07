"""
Bulk-loads the downloaded SynPUF CSV.gz files straight into the OMOP schema
via Postgres COPY (streaming, no need to decompress to disk first). This is
the "Task 1" milestone: a real, OMOP-shaped, ~100k-patient dataset sitting in
Postgres, queryable exactly like the workbook describes.
"""
import gzip
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingestion.download_synpuf import TABLES, download_all  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SCHEMA = "omop"

# SynPUF's CSVs were exported against OMOP CDM v5.3; a handful of columns
# were renamed between v5.3 and v5.4. Confirmed by diffing every CSV header
# against sql/OMOPCDM_postgresql_5.4_ddl.sql — these two tables are the only
# real renames, everything else is just newer v5.4-only columns left NULL.
COLUMN_RENAMES = {
    "visit_occurrence": {
        "admitting_source_concept_id": "admitted_from_concept_id",
        "admitting_source_value": "admitted_from_source_value",
        "discharge_to_concept_id": "discharged_to_concept_id",
        "discharge_to_source_value": "discharged_to_source_value",
    },
    "procedure_occurrence": {
        "qualifier_source_value": "modifier_source_value",
    },
}

# Load order matters once foreign keys are added later; harmless but sensible now too.
LOAD_ORDER = [
    "location", "care_site", "provider", "person", "death", "observation_period",
    "visit_occurrence", "condition_occurrence", "condition_era", "drug_exposure",
    "drug_era", "drug_strength", "procedure_occurrence", "device_exposure",
    "measurement", "observation", "payer_plan_period",
]
assert set(LOAD_ORDER) == set(TABLES), "LOAD_ORDER must match the table list exactly"


def get_conn():
    return psycopg2.connect(
        host=os.environ["PGHOST"], port=os.environ["PGPORT"],
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"],
        dbname=os.environ["PGDATABASE"],
    )


def load_table(conn, csv_gz_path: Path, table: str):
    """
    SynPUF's CSVs were exported against OMOP CDM v5.3, and our schema is the
    current v5.4 DDL — a handful of tables (location, others) have columns
    v5.4 added that v5.3 doesn't (e.g. location.country_concept_id). Rather
    than downgrade the schema, load using each CSV's own header as the
    explicit column list: whatever v5.4 columns aren't in the file are just
    left NULL, exactly as they'd be for a real v5.3 source in production.
    """
    with conn.cursor() as cur:
        cur.execute(f"truncate table {SCHEMA}.{table} cascade;")
        with gzip.open(csv_gz_path, "rt", encoding="utf-8", newline="") as f:
            header_line = f.readline()
            renames = COLUMN_RENAMES.get(table, {})
            columns = [renames.get(c.strip(), c.strip()) for c in header_line.strip().split(",")]
            col_list = ", ".join(columns)
            cur.copy_expert(
                f"COPY {SCHEMA}.{table} ({col_list}) FROM STDIN WITH (FORMAT csv)", f
            )
        cur.execute(f"select count(*) from {SCHEMA}.{table};")
        count = cur.fetchone()[0]
    conn.commit()
    return count


def fhir_data_would_be_wiped(conn) -> int:
    """
    TRUNCATE CASCADE on omop.person (and the clinical tables) wipes anything
    Task 1b merged in, without touching omop._fhir_patient_map -- which is
    exactly how this got orphaned once already: re-running this script after
    a FHIR merge silently destroyed it, and nothing caught it because foreign
    keys are deferred (see README). Returns how many FHIR patients are at risk.
    """
    with conn.cursor() as cur:
        cur.execute("select to_regclass('omop._fhir_patient_map')")
        if cur.fetchone()[0] is None:
            return 0
        cur.execute("select count(*) from omop._fhir_patient_map")
        return cur.fetchone()[0]


def main(size: str = "100k", force: bool = False):
    conn = get_conn()
    at_risk = fhir_data_would_be_wiped(conn)
    if at_risk and not force:
        conn.close()
        print(f"REFUSING TO RUN: {at_risk} FHIR-merged patient(s) exist in omop._fhir_patient_map.")
        print("Re-running this script TRUNCATEs omop.person and the clinical tables, which would")
        print("wipe them (this happened once already -- see README's 'notes from actually running")
        print("this'). If you're certain you want to reload SynPUF and then re-run")
        print("omop/merge_fhir_patients.py afterward, pass --force.")
        sys.exit(1)

    data_dir = download_all(size)  # no-ops for files already on disk

    print(f"\nLoading into Postgres schema '{SCHEMA}'...")
    try:
        for table in LOAD_ORDER:
            csv_gz = data_dir / f"{table}.csv.gz"
            count = load_table(conn, csv_gz, table)
            print(f"  {table:22s} {count:>9,} rows")
    finally:
        conn.close()
    print("\nDone.")
    if at_risk:
        print(f"\nReminder: re-run `python omop/merge_fhir_patients.py` now to restore "
              f"the {at_risk} FHIR-merged patient(s) this just truncated.")


if __name__ == "__main__":
    args = sys.argv[1:]
    force_flag = "--force" in args
    args = [a for a in args if a != "--force"]
    size_arg = args[0] if args else "100k"
    main(size_arg, force=force_flag)
