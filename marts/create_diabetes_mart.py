"""
The "pre-built common question" from the workbook: one row per person, with
every fact a T2D cohort definition needs already joined and flagged, so the
cohort compiler only ever touches this one view — never condition_occurrence
/ measurement / drug_exposure directly. Built against the real omop.* tables
populated by both Task 1a (SynPUF) and Task 1b (FHIR-merged patients).
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

VIEW_SQL = """
create schema if not exists marts;

create or replace view marts.diabetes_mart as
with t2d as (
    select person_id, min(condition_start_date) as t2d_onset_date
    from omop.condition_occurrence
    where condition_concept_id = 201826  -- Type 2 diabetes mellitus
    group by person_id
),
esrd as (
    select distinct person_id
    from omop.condition_occurrence
    where condition_concept_id = 4030518  -- End stage renal disease
),
pregnancy as (
    select distinct person_id
    from omop.condition_occurrence
    where condition_concept_id = 4136529  -- Patient currently pregnant
),
latest_hba1c as (
    select distinct on (person_id)
        person_id,
        value_as_number as hba1c_value,
        measurement_date as hba1c_date
    from omop.measurement
    where measurement_concept_id = 3004410  -- Hemoglobin A1c
    order by person_id, measurement_date desc
),
metformin as (
    select person_id, min(drug_exposure_start_date) as metformin_start_date
    from omop.drug_exposure
    where drug_concept_id = 1503297  -- Metformin
    group by person_id
)
select
    p.person_id,
    p.year_of_birth,
    (date_part('year', current_date) - p.year_of_birth)::int as age,
    (t2d.person_id is not null) as has_t2d,
    t2d.t2d_onset_date,
    h.hba1c_value as latest_hba1c_value,
    h.hba1c_date as latest_hba1c_date,
    (m.person_id is not null) as on_metformin,
    m.metformin_start_date,
    (e.person_id is not null) as has_esrd,
    (pr.person_id is not null) as is_pregnant
from omop.person p
left join t2d on t2d.person_id = p.person_id
left join latest_hba1c h on h.person_id = p.person_id
left join metformin m on m.person_id = p.person_id
left join esrd e on e.person_id = p.person_id
left join pregnancy pr on pr.person_id = p.person_id;
"""


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )
    return create_engine(url)


def main():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(VIEW_SQL))
        total = conn.execute(text("select count(*) from marts.diabetes_mart")).scalar()
        t2d = conn.execute(text("select count(*) from marts.diabetes_mart where has_t2d")).scalar()
    print(f"marts.diabetes_mart ready: {total:,} people, {t2d:,} with a T2D diagnosis.")


if __name__ == "__main__":
    main()
