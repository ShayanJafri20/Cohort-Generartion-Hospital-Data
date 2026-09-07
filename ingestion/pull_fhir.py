"""
Stands in for `ingestion/pull_fhir.py` calling a real hospital's FHIR API with
`_lastUpdated` incremental search. For the demo, "pulling" means reading the
synthetic Bundles Phase 1 generated — same downstream code either way, since
both hand back a Bundle's list of resources.

Real version later: swap `read_local_bundles()` for an actual `requests.get(...)`
call against the hospital's FHIR search endpoint. Nothing past this function
needs to change.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic_fhir"


def read_local_bundles():
    """Yields (source_file_name, bundle_dict) for every synthetic Bundle on disk."""
    for path in sorted(DATA_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            yield path.name, json.load(f)


def validate_bundle(source_file, bundle):
    """
    Chapter 03 concern #6 (nothing checks data before it flows downstream) starts
    right here: quarantine anything malformed instead of crashing the whole run
    or silently letting it through.
    """
    problems = []
    if bundle.get("resourceType") != "Bundle":
        problems.append("not a Bundle")
        return problems
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        if "resourceType" not in res:
            problems.append(f"entry missing resourceType: {res.get('id', '?')}")
        if "id" not in res:
            problems.append(f"entry missing id: {res.get('resourceType', '?')}")
    return problems


if __name__ == "__main__":
    total_resources = 0
    for name, b in read_local_bundles():
        problems = validate_bundle(name, b)
        status = "OK" if not problems else f"QUARANTINED: {problems}"
        n = len(b.get("entry", []))
        total_resources += n
        print(f"{name:35s} {n} resources  {status}")
    print(f"\nTotal resources across all bundles: {total_resources}")
