"""
Loads the vocabulary mapping table into Postgres as a versioned reference
table, purely so cohort runs can stamp *which* vocabulary version produced
them (Chapter 03 concern #3). `mini_concepts.csv` stands in for a real OHDSI
Athena vocabulary download here — same shape either way, so pointing this at
the real download later is a change to the CSV source, not the schema.

Uses its own `vocab_map` schema, deliberately not named `vocabulary` — OMOP's
own CDM already reserves a table called `omop.vocabulary` for the real Athena
release; this is just our lightweight lookup, not that.
"""
import csv
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

VOCAB_CSV = Path(__file__).resolve().parent / "mini_concepts.csv"
VOCAB_VERSION = "demo-mini-vocab-2026-09"  # stand-in for a real Athena release tag


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )
    return create_engine(url)


DDL = """
create schema if not exists vocab_map;

drop table if exists vocab_map.concept_map;
create table vocab_map.concept_map (
    source_system text,
    source_code text,
    standard_concept_id integer,
    standard_concept_name text,
    domain text,
    vocab_version text,
    loaded_at date,
    primary key (source_system, source_code)
);
"""


def load():
    engine = get_engine()
    with open(VOCAB_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["vocab_version"] = VOCAB_VERSION
        r["loaded_at"] = date.today().isoformat()

    with engine.begin() as conn:
        conn.execute(text(DDL))
        conn.execute(text("""
            insert into vocab_map.concept_map
                (source_system, source_code, standard_concept_id, standard_concept_name,
                 domain, vocab_version, loaded_at)
            values
                (:source_system, :source_code, :standard_concept_id, :standard_concept_name,
                 :domain, :vocab_version, :loaded_at)
        """), rows)

    print(f"Loaded {len(rows)} concept mappings, tagged as vocabulary version '{VOCAB_VERSION}'.")


if __name__ == "__main__":
    load()
