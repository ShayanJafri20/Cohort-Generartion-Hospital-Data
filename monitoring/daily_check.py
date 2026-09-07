"""
"Yesterday 1 million observations arrived; today only 10,000" — this is the
script that would actually catch that (Chapter 03 concern #9). Logs today's
row counts across the core OMOP tables, then flags a drop of more than 30%
against the previous logged run instead of staying silent.

Also logs the current git commit and vocabulary version alongside the counts
— the same run-log table doubles as a lightweight audit trail of "what did
the warehouse look like, and from which code, at any point in time."
"""
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DROP_ALERT_THRESHOLD = 0.30  # flag if a count falls more than 30% run-over-run

DDL = """
create schema if not exists monitoring;

create table if not exists monitoring.pipeline_run_log (
    run_id serial primary key,
    run_at timestamp not null default now(),
    git_commit text,
    vocabulary_version text,
    person_count integer,
    condition_count integer,
    measurement_count integer,
    drug_exposure_count integer,
    status text,
    note text
);
"""


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


def main():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(DDL))

        counts = {
            "person_count": conn.execute(text("select count(*) from omop.person")).scalar(),
            "condition_count": conn.execute(text("select count(*) from omop.condition_occurrence")).scalar(),
            "measurement_count": conn.execute(text("select count(*) from omop.measurement")).scalar(),
            "drug_exposure_count": conn.execute(text("select count(*) from omop.drug_exposure")).scalar(),
        }
        vocab_version = conn.execute(
            text("select distinct vocab_version from vocab_map.concept_map limit 1")
        ).scalar()

        previous = conn.execute(text("""
            select person_count, condition_count, measurement_count, drug_exposure_count
            from monitoring.pipeline_run_log
            order by run_at desc
            limit 1
        """)).mappings().first()

        alerts = []
        if previous:
            for key, current_value in counts.items():
                prev_value = previous[key]
                if prev_value and current_value < prev_value * (1 - DROP_ALERT_THRESHOLD):
                    alerts.append(
                        f"{key}: {prev_value} -> {current_value} "
                        f"({(1 - current_value / prev_value):.0%} drop)"
                    )

        status = "ALERT" if alerts else "OK"
        conn.execute(text("""
            insert into monitoring.pipeline_run_log
                (git_commit, vocabulary_version, person_count, condition_count,
                 measurement_count, drug_exposure_count, status, note)
            values
                (:git_commit, :vocab_version, :person_count, :condition_count,
                 :measurement_count, :drug_exposure_count, :status, :note)
        """), {
            "git_commit": git_commit_hash(),
            "vocab_version": vocab_version,
            **counts,
            "status": status,
            "note": "; ".join(alerts) if alerts else None,
        })

    print(f"Status: {status}")
    for k, v in counts.items():
        print(f"  {k}: {v:,}")
    if alerts:
        print("\nALERTS:")
        for a in alerts:
            print(f"  - {a}")
        sys.exit(1)  # non-zero exit so the orchestrator (and Task Scheduler) can flag the run as failed
    else:
        print("\nNo anomalies versus the previous run (or this is the first run).")


if __name__ == "__main__":
    main()
