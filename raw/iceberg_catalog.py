"""
The Iceberg "raw" layer, self-hosted, free: catalog metadata lives in a local
SQLite file, actual data files live on local disk as Parquet. No Spark, no JVM,
no Docker required for this layer at all — just PyIceberg.

Later: point the catalog at Postgres instead of SQLite, and the warehouse dir
at Azure Data Lake instead of local disk — this module is the one place that
would change; nothing downstream needs to know.
"""
from pathlib import Path

from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField, StringType, TimestampType

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CATALOG_DB = PROJECT_ROOT / "data" / "iceberg_catalog.db"
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "iceberg_warehouse"

RAW_NAMESPACE = "bronze"
RAW_TABLE = "fhir_resources"

RAW_SCHEMA = Schema(
    NestedField(1, "resource_type", StringType(), required=True),
    NestedField(2, "resource_id", StringType(), required=True),
    NestedField(3, "patient_id", StringType(), required=False),
    NestedField(4, "raw_json", StringType(), required=True),
    NestedField(5, "source_file", StringType(), required=True),
    NestedField(6, "batch_id", StringType(), required=True),
    NestedField(7, "ingested_at", TimestampType(), required=True),
)


def get_catalog():
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    CATALOG_DB.parent.mkdir(parents=True, exist_ok=True)
    return SqlCatalog(
        "local",
        **{
            "uri": f"sqlite:///{CATALOG_DB}",
            "warehouse": f"file://{WAREHOUSE_DIR.as_posix()}",
        },
    )


def get_or_create_raw_table():
    catalog = get_catalog()
    if (RAW_NAMESPACE,) not in [ns for ns in catalog.list_namespaces()]:
        catalog.create_namespace(RAW_NAMESPACE)
    identifier = f"{RAW_NAMESPACE}.{RAW_TABLE}"
    if catalog.table_exists(identifier):
        return catalog.load_table(identifier)
    return catalog.create_table(identifier, schema=RAW_SCHEMA)


if __name__ == "__main__":
    table = get_or_create_raw_table()
    print(f"Raw Iceberg table ready: {table.name()}")
    print(f"  catalog db : {CATALOG_DB}")
    print(f"  warehouse  : {WAREHOUSE_DIR}")
