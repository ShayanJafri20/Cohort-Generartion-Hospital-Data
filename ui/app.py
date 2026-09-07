"""
A local dashboard over everything the pipeline already does — this adds no
new logic, it just makes the existing scripts (omop/, cohort/, monitoring/)
visible instead of terminal-only. Every section is labeled with which
architecture layer it's showing, matching docs/architecture-workbook.html.

Run: .venv\\Scripts\\python.exe -m streamlit run ui\\app.py
"""
import csv
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from cohort.compile_sql import compile_to_sql  # noqa: E402
from cohort.llm_draft import draft_spec, MODEL as GEMINI_MODEL  # noqa: E402
from cohort.validate_spec import validate_spec  # noqa: E402
from raw.iceberg_catalog import get_or_create_raw_table  # noqa: E402

st.set_page_config(page_title="Cohort Platform", layout="wide")


@st.cache_resource
def get_engine():
    import os
    url = (
        f"postgresql+psycopg2://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )
    return create_engine(url)


def q(sql, params=None):
    with get_engine().connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})


def scalar(sql):
    with get_engine().connect() as conn:
        return conn.execute(text(sql)).scalar()


st.title("Cohort Generation Platform")
st.caption(
    "Local dashboard over the pipeline documented in "
    "`docs/architecture-workbook.html` and `docs/cohort-pipeline-proposal.md`."
)

tab_overview, tab_data, tab_vocab, tab_cohort = st.tabs(
    ["Overview & pipeline runs", "OMOP data explorer", "Vocabulary mapping", "Cohort builder (Task 2)"]
)

# ---------------------------------------------------------------- Overview
with tab_overview:
    st.subheader("OMOP warehouse — current row counts")
    st.caption("Layer: `omop.*` tables in Postgres (Task 1a SynPUF + Task 1b FHIR-merged)")

    try:
        counts = q("""
            select 'person' as table_name, count(*) as rows from omop.person
            union all select 'condition_occurrence', count(*) from omop.condition_occurrence
            union all select 'measurement', count(*) from omop.measurement
            union all select 'drug_exposure', count(*) from omop.drug_exposure
            union all select 'visit_occurrence', count(*) from omop.visit_occurrence
        """)
        cols = st.columns(len(counts))
        for col, (_, row) in zip(cols, counts.iterrows()):
            col.metric(row["table_name"], f"{row['rows']:,}")
    except Exception as e:
        st.error(f"Can't reach Postgres — is `docker compose up -d` running? ({e})")
        st.stop()

    fhir_count = scalar("select count(*) from omop._fhir_patient_map")
    st.caption(f"Of the person total, **{fhir_count}** came from the FHIR pipeline (Task 1b); "
               f"the rest are from the bulk-loaded SynPUF dataset (Task 1a).")

    st.divider()
    st.subheader("Pipeline run history")
    st.caption("Layer: `monitoring.pipeline_run_log` — written by `monitoring/daily_check.py`")

    if st.button("▶ Run the pipeline now", type="primary"):
        with st.spinner("Running orchestration/run_pipeline.py — this runs every repeatable step..."):
            result = subprocess.run(
                [str(ROOT / ".venv" / "Scripts" / "python.exe"), "orchestration/run_pipeline.py"],
                cwd=ROOT, capture_output=True, text=True,
            )
        status = "✅ Succeeded" if result.returncode == 0 else "❌ Failed"
        st.markdown(f"**{status}** (exit code {result.returncode})")
        with st.expander("Full output", expanded=(result.returncode != 0)):
            st.code(result.stdout + "\n" + result.stderr)
        st.cache_resource.clear()
        st.rerun()

    runs = q("select * from monitoring.pipeline_run_log order by run_at desc limit 20")
    if runs.empty:
        st.info("No runs logged yet — click the button above, or run `orchestration/run_pipeline.py`.")
    else:
        st.dataframe(runs, use_container_width=True, hide_index=True)

# ------------------------------------------------------------ Data explorer
with tab_data:
    st.subheader("Browse the OMOP tables")
    st.caption("Layer: `omop.*` — the merged warehouse both Task 1a and Task 1b write into")

    table_choice = st.selectbox(
        "Table", ["person", "condition_occurrence", "measurement", "drug_exposure", "visit_occurrence"]
    )
    fhir_only = st.checkbox("FHIR-sourced patients only (Task 1b, not SynPUF)", value=True)
    limit = st.slider("Row limit", 10, 500, 100)

    join_clause = "join omop._fhir_patient_map m on m.person_id = t.person_id" if fhir_only else ""
    df = q(f"select t.* from omop.{table_choice} t {join_clause} order by 1 limit :limit", {"limit": limit})
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"Showing up to {limit} rows" + (" (FHIR-sourced only)" if fhir_only else " (all sources)"))

    if table_choice == "person":
        st.subheader("FHIR patient lineage")
        st.caption("Layer: `omop._fhir_patient_map` — traces every FHIR-sourced row back to its source id (Ch.03 #1)")
        st.dataframe(q("select * from omop._fhir_patient_map order by person_id"), use_container_width=True, hide_index=True)

# ------------------------------------------------------------- Vocabulary
with tab_vocab:
    st.subheader("Vocabulary mapping table")
    st.caption("Layer: `vocab_map.concept_map` — stands in for a real OHDSI Athena download")
    st.dataframe(q("select * from vocab_map.concept_map"), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Unmapped source codes")
    st.caption("Layer: raw Iceberg table, scanned live — the Chapter 03 #2 check, not just a report")

    vocab_csv = ROOT / "vocabulary" / "mini_concepts.csv"
    with open(vocab_csv, newline="", encoding="utf-8") as f:
        vocab_lookup = {(r["source_system"], r["source_code"]) for r in csv.DictReader(f)}

    CODING_PATHS = {
        "Condition": lambda r: r.get("code", {}).get("coding", []),
        "Observation": lambda r: r.get("code", {}).get("coding", []),
        "MedicationStatement": lambda r: r.get("medicationCodeableConcept", {}).get("coding", []),
    }
    raw_table = get_or_create_raw_table()
    latest = {}
    for row in raw_table.scan().to_arrow().to_pylist():
        latest[(row["resource_type"], row["resource_id"])] = row

    unmapped_rows = []
    for row in latest.values():
        if row["resource_type"] not in CODING_PATHS:
            continue
        resource = json.loads(row["raw_json"])
        codings = CODING_PATHS[row["resource_type"]](resource)
        if codings and not any((c.get("system"), c.get("code")) in vocab_lookup for c in codings):
            unmapped_rows.append({
                "patient_id": row["patient_id"], "resource_type": row["resource_type"],
                "resource_id": row["resource_id"],
                "code": codings[0].get("code"), "display": codings[0].get("display"),
            })

    if unmapped_rows:
        st.warning(f"{len(unmapped_rows)} resource(s) have no standard-concept match — "
                   f"these patients would silently disappear from any cohort built on this field.")
        st.dataframe(pd.DataFrame(unmapped_rows), use_container_width=True, hide_index=True)
    else:
        st.success("No unmapped codes found in the raw layer.")

# --------------------------------------------------------------- Cohort
with tab_cohort:
    st.subheader("Draft a cohort from a protocol description")
    st.caption("Layer: `cohort/llm_draft.py` — Gemini drafts a spec, it never touches SQL directly")

    default_protocol = (
        "Inclusion: age 40 or older, diagnosed with Type 2 diabetes, HbA1c above 7%, "
        "currently on Metformin. Exclusion: severe (end-stage) renal disease, pregnancy."
    )
    protocol_text = st.text_area("Protocol / eligibility description", value=default_protocol, height=100)

    if "spec" not in st.session_state:
        st.session_state.spec = None

    col1, col2 = st.columns(2)
    if col1.button(f"🤖 Draft with {GEMINI_MODEL}"):
        with st.spinner("Calling Gemini..."):
            try:
                st.session_state.spec = draft_spec(protocol_text)
                st.success("Drafted and schema-validated.")
            except Exception as e:
                st.error(f"Draft failed: {e}")

    if col2.button("📝 Use example_spec.json instead"):
        st.session_state.spec = json.loads((ROOT / "cohort" / "example_spec.json").read_text())

    if st.session_state.spec:
        st.json(st.session_state.spec)

        st.subheader("Compiled SQL")
        st.caption("Layer: `cohort/compile_sql.py` — deterministic, no LLM involved in this step")
        try:
            sql = compile_to_sql(st.session_state.spec)
            st.code(sql, language="sql")

            if st.button("▶ Run this cohort query", type="primary"):
                df = q(sql)
                vocab_version = scalar("select distinct vocab_version from vocab_map.concept_map limit 1")
                st.success(f"**{len(df)} patients matched** — vocabulary version `{vocab_version}`")
                st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Spec failed validation, refused to compile: {e}")

    st.divider()
    st.subheader("Try to break it")
    st.caption("Proves the AI/SQL boundary from Chapter 03 — this can never reach the database")
    if st.button("💉 Submit a spec with a SQL-injection payload"):
        bad = {
            "cohort_name": "malicious", "inclusion": {
                "min_age": 40, "concept": "t2d",
                "measurement": {"type": "hba1c", "operator": "; DROP TABLE person; --", "value": 7},
                "drug_exposure": "metformin",
            }, "exclusion": [],
        }
        try:
            validate_spec(bad)
            st.error("This should have been rejected — validation gap!")
        except Exception as e:
            st.success(f"Correctly rejected before touching SQL: {e}")
