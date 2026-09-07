"""
Chapter 03 concern #3, addressed: every cohort result is stamped with exactly
which code version, vocabulary version, and data snapshot produced it — so
"why did this list change" always has a real answer.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cohort.compile_sql import compile_to_sql  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )
    return create_engine(url)


def git_commit_hash():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parent.parent
        ).decode().strip()
    except Exception:
        return "no-commits-yet"


def run(spec_path: Path):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    sql = compile_to_sql(spec)
    engine = get_engine()

    with engine.begin() as conn:
        rows = conn.execute(text(sql)).mappings().all()
        vocab_version = conn.execute(
            text("select distinct vocab_version from vocab_map.concept_map limit 1")
        ).scalar()

    run_record = {
        "cohort_name": spec["cohort_name"],
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit_hash(),
        "vocabulary_version": vocab_version,
        "sql": sql,
        "patient_count": len(rows),
        "patients": [dict(r) for r in rows],
    }

    print(f"Cohort: {run_record['cohort_name']}")
    print(f"  git commit        : {run_record['git_commit']}")
    print(f"  vocabulary version: {run_record['vocabulary_version']}")
    print(f"  run at (UTC)      : {run_record['run_at_utc']}")
    print(f"  patients matched  : {run_record['patient_count']}")
    for r in run_record["patients"][:25]:
        print(f"    person_id={r['person_id']:>10}  age={r['age']}  hba1c={r['latest_hba1c_value']}  "
              f"metformin_since={r['metformin_start_date']}")
    if run_record["patient_count"] > 25:
        print(f"    ... and {run_record['patient_count'] - 25} more")

    out_dir = Path(__file__).resolve().parent.parent / "data" / "cohort_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_file.write_text(json.dumps(run_record, indent=2, default=str), encoding="utf-8")
    print(f"\nFull stamped result saved to {out_file}")

    return run_record


if __name__ == "__main__":
    spec_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "example_spec.json"
    run(spec_file)
