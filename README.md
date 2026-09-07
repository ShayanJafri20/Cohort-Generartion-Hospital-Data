# Cohort-Generartion-Hospital-Data

RWD/OMOP cohort-generation platform — FHIR ingestion, OMOP CDM mapping, and an AI cohort-drafting assistant, built free/local-first.

- **Architecture & reasoning:** [`docs/architecture-workbook.html`](docs/architecture-workbook.html), [`docs/cohort-pipeline-proposal.md`](docs/cohort-pipeline-proposal.md)
- **OMOP CDM v5.4 DDL** (official OHDSI): [`sql/`](sql/)

## Status

Building step by step, per task:

- [x] **Task 1a — SynPUF into OMOP**: CMS DE-SynPUF (100k patients, real OMOP CDM v5.3 data) downloaded from AWS Open Data and bulk-loaded into a Postgres `omop` schema built from the official OHDSI v5.4 DDL — **~58M rows loaded across 17 tables**, verified.
- [x] **Task 1b — FHIR → OMOP mapping**: 13 hand-designed synthetic FHIR patients → Iceberg (raw, immutable) → vocabulary-mapped (`vocabulary/mini_concepts.csv`) → merged directly into the *same* `omop.person` / `condition_occurrence` / `measurement` / `drug_exposure` tables SynPUF populated, with non-colliding surrogate keys and a rerun-safe `omop._fhir_patient_map`. Verified: the one deliberately unmapped patient correctly lands as `condition_concept_id = 0` instead of being silently miscounted as T2D.
- [x] **Task 2 — AI cohort assistant**: protocol text → Gemini (free tier) drafts a structured `CohortSpec` → JSON-Schema-validated → deterministically compiled to SQL → run against `marts.diabetes_mart` (built on the merged OMOP tables) → result stamped with git commit + vocabulary version. Verified: a tampered spec with a SQL-injection payload is rejected by schema validation before it ever reaches a query, and the real query returns exactly the 5 patients designed to qualify.

## Setup

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then edit PGPORT if 5432/5433 are already taken locally
docker compose up -d
python omop/apply_ddl.py             # creates the OMOP CDM v5.4 schema (tables, PKs, indices)
python omop/load_synpuf.py           # downloads + bulk-loads the 100k-patient SynPUF dataset
python ingestion/generate_synthetic_data.py  # writes 13 synthetic FHIR bundles
python raw/load_raw.py               # raw JSON -> immutable Iceberg snapshot
python vocabulary/mapping_report.py  # flags any source codes with no concept mapping
python omop/merge_fhir_patients.py   # vocabulary-maps + merges those patients into omop.*
python vocabulary/athena_loader.py   # loads the vocab version table (for run stamping)
python marts/create_diabetes_mart.py # builds the mart view cohort queries run against

# Task 2 — set GEMINI_API_KEY in .env first (free, no billing: https://aistudio.google.com/apikey)
python cohort/llm_draft.py     # protocol text -> structured spec (falls back without a key)
python cohort/run_cohort.py    # spec -> validated -> compiled to SQL -> executed -> stamped
```

### Notes from actually running this

- **Port conflicts are likely.** This dev machine had two unrelated native Postgres
  processes already bound to 5432 and 5433. `docker-compose.yml` reads `PGPORT` from
  `.env`, so just pick a free port there — no code changes needed.
- **SynPUF's CSVs are OMOP CDM v5.3, not v5.4.** `omop/load_synpuf.py` loads each
  table using that CSV's own header as the column list (so newer v5.4-only columns
  like `location.country_concept_id` are simply left NULL), and applies a small
  rename map for the two columns OHDSI actually renamed between versions
  (`visit_occurrence.admitting_source_*` → `admitted_from_*`, etc.) — confirmed by
  diffing every CSV header against the DDL, not by guessing.
- **`OMOPCDM_postgresql_5.4_constraints.sql` is intentionally not applied yet** —
  it foreign-keys every `*_concept_id` column to `concept`/`vocabulary`, which
  aren't loaded until the real OHDSI Athena vocabulary is (a separate step).
- **SynPUF alone can't populate this particular cohort.** DE-SynPUF is 2008–2010
  Medicare *claims* data — no lab result values, and its drug claims don't hit
  the plain ingredient-level RxNorm concept (1503297) this demo cohort filters
  on. So `cohort/run_cohort.py`'s 5 matches are all FHIR-merged patients; that's
  expected, not a bug — worth knowing before assuming a cohort query "isn't
  finding" real SynPUF patients that were never going to qualify on this data.
- **Gemini, not Claude, for Task 2** — `google-genai` (the current SDK; the
  older `google-generativeai` package is deprecated), `gemini-2.5-flash`
  (confirmed free-tier eligible), structured output via `response_json_schema`
  passing our existing `cohort_spec.schema.json` directly, no Pydantic needed.
