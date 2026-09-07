# Cohort-Generartion-Hospital-Data

RWD/OMOP cohort-generation platform — FHIR ingestion, OMOP CDM mapping, and an AI cohort-drafting assistant, built free/local-first.

- **Architecture & reasoning:** [`docs/architecture-workbook.html`](docs/architecture-workbook.html), [`docs/cohort-pipeline-proposal.md`](docs/cohort-pipeline-proposal.md)
- **OMOP CDM v5.4 DDL** (official OHDSI): [`sql/`](sql/)

## Status

Building step by step, per task:

- [ ] **Task 1 — OMOP mapping**: FHIR/synthetic ingestion → Iceberg (raw) → vocabulary mapping → OMOP CDM in Postgres, plus the CMS DE-SynPUF (100k patient) OMOP dataset loaded for scale
- [ ] **Task 2 — AI cohort assistant**: protocol → structured cohort spec → validated → compiled to SQL → executed against OMOP

## Setup

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
docker compose up -d
```
