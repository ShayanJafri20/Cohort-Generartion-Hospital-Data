# Cohort-Generartion-Hospital-Data

RWD/OMOP cohort-generation platform — FHIR ingestion, OMOP CDM mapping, and an AI cohort-drafting assistant, built free/local-first.

- **Architecture & reasoning:** [`docs/architecture-workbook.html`](docs/architecture-workbook.html), [`docs/cohort-pipeline-proposal.md`](docs/cohort-pipeline-proposal.md)
- **OMOP CDM v5.4 DDL** (official OHDSI): [`sql/`](sql/)

## Status

Building step by step, per task:

- [x] **Task 1a — SynPUF into OMOP**: CMS DE-SynPUF (100k patients, real OMOP CDM v5.3 data) downloaded from AWS Open Data and bulk-loaded into a Postgres `omop` schema built from the official OHDSI v5.4 DDL — **~58M rows loaded across 17 tables**, verified.
- [x] **Task 1b — FHIR → OMOP mapping**: 13 hand-designed synthetic FHIR patients → Iceberg (raw, immutable) → vocabulary-mapped (`vocabulary/mini_concepts.csv`) → merged directly into the *same* `omop.person` / `condition_occurrence` / `measurement` / `drug_exposure` tables SynPUF populated, with non-colliding surrogate keys and a rerun-safe `omop._fhir_patient_map`. Verified: the one deliberately unmapped patient correctly lands as `condition_concept_id = 0` instead of being silently miscounted as T2D.
- [x] **Task 2 — AI cohort assistant**: protocol text → Gemini (free tier) drafts a structured `CohortSpec` → JSON-Schema-validated → deterministically compiled to SQL → run against `marts.diabetes_mart` (built on the merged OMOP tables) → result stamped with git commit + vocabulary version. Verified: a tampered spec with a SQL-injection payload is rejected by schema validation before it ever reaches a query, and the real query returns exactly the 5 patients designed to qualify.
- [x] **Orchestration + monitoring**: `orchestration/run_pipeline.py` is the single command (what Task Scheduler would call nightly) that runs the repeatable steps in order and stops at the first real failure; `monitoring/daily_check.py` logs row counts every run and flags a >30% drop against the previous run instead of staying silent. Verified across two consecutive full runs with stable, correct counts (and a real bug caught and fixed in the process — see notes below).
- [x] **UI**: `ui/app.py`, a local Streamlit dashboard over everything above — pipeline run history with a one-click "run now," an OMOP data browser, the vocabulary mapping report, and the full cohort builder (draft with Gemini, view the compiled SQL, run it, try to break it with an injection payload). No new logic, just makes the existing scripts visible.

## Setup

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then edit PGPORT if 5432/5433 are already taken locally
docker compose up -d
# One-time setup (schema creation + a static historical bulk load — not re-run nightly)
python omop/apply_ddl.py             # creates the OMOP CDM v5.4 schema (tables, PKs, indices)
python omop/load_synpuf.py           # downloads + bulk-loads the 100k-patient SynPUF dataset
python vocabulary/athena_loader.py   # loads the vocab version table (for run stamping)

# Task 2 — set GEMINI_API_KEY in .env first (free, no billing: https://aistudio.google.com/apikey)
python cohort/llm_draft.py     # protocol text -> structured spec (falls back without a key)
python cohort/run_cohort.py    # spec -> validated -> compiled to SQL -> executed -> stamped

# The repeatable pipeline (what Task Scheduler runs nightly) — one command:
python orchestration/run_pipeline.py

# The UI — everything above, but visual
python -m streamlit run ui/app.py
```
Opens at `http://localhost:8501`.

### Scheduling it for real

`orchestration/run_pipeline.py` runs the steps; it doesn't register itself with
Task Scheduler. To actually schedule it nightly at 2 AM (run once, as admin if needed):

```powershell
schtasks /create /tn "CohortPipeline" /tr "\"C:\Users\admins2\Desktop\Cohort Generation\.venv\Scripts\python.exe\" \"C:\Users\admins2\Desktop\Cohort Generation\orchestration\run_pipeline.py\"" /sc daily /st 02:00
```

`monitoring/daily_check.py` exits non-zero on an alert, so a failed Task
Scheduler run shows up in Task Scheduler's own history — no NSSM needed, per
the workbook's Chapter 04 reasoning.

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
  older `google-generativeai` package is deprecated), structured output via
  `response_json_schema` passing our existing `cohort_spec.schema.json`
  directly, no Pydantic needed. Model name needed a live fix: `gemini-2.5-flash`
  (what the docs said was free-tier eligible) turned out to already be
  deprecated for new users by the time this ran — the API's own error message
  named the replacement (`gemini-3.6-flash`), which is what's actually in the
  code now. Worth re-checking if this breaks again; Google moves fast here.
- **The raw Iceberg layer is append-only on purpose, and that has a sharp
  edge**: re-running ingestion adds a new snapshot on top of the last one, so
  a resource pulled again unchanged shows up twice in `table.scan()`. The
  first version of `omop/merge_fhir_patients.py` didn't account for this and
  silently doubled every condition/measurement/drug row on the second
  pipeline run. Fixed by collapsing to one row per `(resource_type,
  resource_id)` — latest `ingested_at` wins — before merging; the same fix
  went into `vocabulary/mapping_report.py`, which had the identical bug.
  Caught by actually running the pipeline twice and checking row counts, not
  by code review.
- **A real orphaned-data incident, and what it says about deferred FK
  constraints.** Following this README's own setup steps in order a second
  time — specifically re-running `omop/load_synpuf.py` after Task 1b had
  already merged the 13 FHIR patients — silently wiped `omop.person` back to
  just the 100k SynPUF rows (that script `TRUNCATE`s before reloading).
  `omop._fhir_patient_map` wasn't touched, so a later `merge_fhir_patients.py`
  run saw those 13 patients as "already existing," skipped recreating their
  `person` rows, but still deleted-and-reinserted their condition/measurement/
  drug rows — creating rows that pointed at a `person_id` with no `person`
  row behind it. Nothing caught this, because `OMOPCDM_postgresql_5.4_constraints.sql`
  is deliberately not applied yet (see above) — this is exactly the failure
  mode that gap leaves open, now observed for real instead of just reasoned
  about. Fixed two ways: `merge_fhir_patients.py` now checks whether the
  `person` row actually exists rather than trusting the map, and self-heals
  if it doesn't; `load_synpuf.py` now refuses to run (without `--force`) if
  any FHIR-merged patients exist, since re-running it is what caused this.
  Repaired and reverified against live data — `omop.person` back to 100,013,
  zero orphaned rows, cohort query back to the correct 5 matches.
