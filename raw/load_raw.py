"""
Chapter 03 concern #1, addressed: every resource from every bundle gets written
into an Iceberg table exactly as received, as one new immutable snapshot. Six
months from now, `table.history()` still shows exactly what this run wrote and
when — nothing here can be silently overwritten.
"""
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingestion.pull_fhir import read_local_bundles, validate_bundle  # noqa: E402
from raw.iceberg_catalog import get_or_create_raw_table  # noqa: E402


def patient_id_of(resource):
    """Every resource in these bundles points back to its Patient via `subject`."""
    if resource.get("resourceType") == "Patient":
        return resource.get("id")
    ref = resource.get("subject", {}).get("reference", "")
    return ref.split("/")[-1] if "/" in ref else None


def flatten_to_rows(source_file, bundle, batch_id, ingested_at):
    rows = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rows.append({
            "resource_type": res.get("resourceType", "Unknown"),
            "resource_id": res.get("id", "unknown"),
            "patient_id": patient_id_of(res),
            "raw_json": json.dumps(res),
            "source_file": source_file,
            "batch_id": batch_id,
            "ingested_at": ingested_at,
        })
    return rows


def main():
    table = get_or_create_raw_table()
    batch_id = str(uuid.uuid4())
    ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)

    all_rows = []
    quarantined = 0
    for source_file, bundle in read_local_bundles():
        problems = validate_bundle(source_file, bundle)
        if problems:
            quarantined += 1
            print(f"  SKIPPED {source_file}: {problems}")
            continue
        all_rows.extend(flatten_to_rows(source_file, bundle, batch_id, ingested_at))

    if not all_rows:
        print("Nothing to load.")
        return

    arrow_table = pa.Table.from_pylist(all_rows, schema=table.schema().as_arrow())
    table.append(arrow_table)

    print(f"Batch {batch_id}")
    print(f"  wrote {len(all_rows)} resource rows into a new Iceberg snapshot")
    print(f"  quarantined {quarantined} bundle(s)")
    print(f"  table now has {len(table.history())} snapshot(s) total")


if __name__ == "__main__":
    main()
