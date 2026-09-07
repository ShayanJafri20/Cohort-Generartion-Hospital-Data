"""
The single entry point Task Scheduler (or cron) would call on a schedule —
replaces NSSM + ad-hoc scripts with one command that stops at the first real
failure instead of silently continuing on bad data.

Deliberately only the *repeatable* steps: pulling new source data, mapping it,
merging it into OMOP, refreshing the mart, and checking for anomalies. The
one-time setup steps — omop/apply_ddl.py (schema creation) and
omop/load_synpuf.py (a static historical bulk load, not something re-pulled
nightly) — are run once by hand, not on every scheduled run; see README.

This script only runs the steps and stops on failure — it does not itself
install anything into Task Scheduler. To actually schedule it, see the
`schtasks` command in README.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"

STEPS = [
    ("Pull + validate FHIR bundles", ["ingestion/generate_synthetic_data.py"]),
    ("Validate before loading", ["ingestion/pull_fhir.py"]),
    ("Load raw Iceberg snapshot", ["raw/load_raw.py"]),
    ("Vocabulary mapping report", ["vocabulary/mapping_report.py"]),
    ("Merge into OMOP", ["omop/merge_fhir_patients.py"]),
    ("Refresh diabetes_mart", ["marts/create_diabetes_mart.py"]),
    ("Daily anomaly check", ["monitoring/daily_check.py"]),
]


def run_step(label, args):
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    result = subprocess.run([str(PY), *args], cwd=ROOT)
    if result.returncode != 0:
        print(f"\nFAILED at: {label} (exit code {result.returncode})")
        sys.exit(result.returncode)


def main():
    for label, args in STEPS:
        run_step(label, args)
    print(f"\n{'=' * 60}\nPipeline run complete.\n{'=' * 60}")


if __name__ == "__main__":
    main()
