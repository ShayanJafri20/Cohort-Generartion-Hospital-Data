"""
Applies the official OHDSI OMOP CDM v5.4 Postgres DDL to the `omop` schema:
tables, primary keys, and indices.

Deliberately NOT applying OMOPCDM_postgresql_5.4_constraints.sql yet — those
are foreign keys from every *_concept_id column to `concept`, `vocabulary`,
etc., which only exist once the real OHDSI Athena vocabulary is loaded
(docs/architecture-workbook.html, vocabulary chapter). Applying it now would
fail on tables we haven't loaded. Re-run this with constraints once that's
in place.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
SCHEMA = "omop"

FILES = [
    "OMOPCDM_postgresql_5.4_ddl.sql",
    "OMOPCDM_postgresql_5.4_primary_keys.sql",
    "OMOPCDM_postgresql_5.4_indices.sql",
]


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )
    return create_engine(url)


def statements_from(sql_text: str):
    sql_text = sql_text.replace("@cdmDatabaseSchema", SCHEMA)
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    sql_text = "\n".join(lines)
    return [p.strip() for p in sql_text.split(";") if p.strip()]


def main():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"create schema if not exists {SCHEMA}"))
        for fname in FILES:
            content = (SQL_DIR / fname).read_text(encoding="utf-8")
            stmts = statements_from(content)
            print(f"{fname}: {len(stmts)} statements")
            for stmt in stmts:
                conn.execute(text(stmt))
    print(f"\nOMOP CDM v5.4 schema ready in Postgres schema '{SCHEMA}' "
          f"(tables + primary keys + indices; constraints deferred).")


if __name__ == "__main__":
    main()
