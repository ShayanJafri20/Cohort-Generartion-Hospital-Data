"""
Chapter 03 concern #2, addressed: report every source (system, code) pair with
no standard-concept match, instead of letting a mis-coded diagnosis silently
vanish from every cohort it should have been part of.

`mini_concepts.csv` here stands in for the real OHDSI Athena vocabulary
download (a multi-GB release, not something to fake for a demo) — same
lookup shape, so swapping in the real thing later is a one-line change in
`vocabulary/athena_loader.py`, not a rewrite of this report. All five concept
IDs in this mini table are real, current OMOP standard concepts — cross-checked
against the ~58M-row SynPUF dataset already loaded (e.g. concept 201826 for
Type 2 diabetes covers 525,283 real condition rows there).
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from raw.iceberg_catalog import get_or_create_raw_table  # noqa: E402

VOCAB_CSV = Path(__file__).resolve().parent / "mini_concepts.csv"

CODING_PATHS = {
    "Condition": lambda r: r.get("code", {}).get("coding", []),
    "Observation": lambda r: r.get("code", {}).get("coding", []),
    "MedicationStatement": lambda r: r.get("medicationCodeableConcept", {}).get("coding", []),
}


def load_vocab():
    vocab = {}
    with open(VOCAB_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vocab[(row["source_system"], row["source_code"])] = row
    return vocab


def main():
    vocab = load_vocab()
    table = get_or_create_raw_table()

    scanned = 0
    unmapped = []
    for row in table.scan().to_arrow().to_pylist():
        resource_type = row["resource_type"]
        if resource_type not in CODING_PATHS:
            continue
        resource = json.loads(row["raw_json"])
        codings = CODING_PATHS[resource_type](resource)
        if not codings:
            continue
        scanned += 1
        matched = any((c.get("system"), c.get("code")) in vocab for c in codings)
        if not matched:
            unmapped.append({
                "patient_id": row["patient_id"],
                "resource_type": resource_type,
                "resource_id": row["resource_id"],
                "codings": [(c.get("system"), c.get("code"), c.get("display")) for c in codings],
            })

    print(f"Scanned {scanned} codeable resources against {len(vocab)} known mappings.\n")
    if unmapped:
        print(f"UNMAPPED - {len(unmapped)} resource(s) have no standard concept match:")
        for u in unmapped:
            print(f"  patient={u['patient_id']}  {u['resource_type']}/{u['resource_id']}")
            for system, code, display in u["codings"]:
                print(f"      {system}  {code}   \"{display}\"")
        print("\nThese patients would silently disappear from any cohort built on this")
        print("condition/drug/measurement unless someone reviews and maps them.")
    else:
        print("No unmapped codes found.")


if __name__ == "__main__":
    main()
