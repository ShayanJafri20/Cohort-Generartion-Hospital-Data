"""
Whatever produced a cohort spec — a human, or the LLM in `llm_draft.py` — it
passes through here before anything is allowed to touch a database. This is
the enforcement point for the whole "AI drafts, code decides" boundary.
"""
import json
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent / "cohort_spec.schema.json"


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_spec(spec: dict):
    """Raises jsonschema.ValidationError with a precise, actionable message on failure."""
    jsonschema.validate(instance=spec, schema=load_schema())
    return spec


if __name__ == "__main__":
    example = json.loads((Path(__file__).resolve().parent / "example_spec.json").read_text())
    validate_spec(example)
    print("example_spec.json is valid against cohort_spec.schema.json")

    bad = {"cohort_name": "malicious", "inclusion": {"min_age": 40, "concept": "t2d",
           "measurement": {"type": "hba1c", "operator": "; DROP TABLE person; --", "value": 7},
           "drug_exposure": "metformin"}, "exclusion": []}
    try:
        validate_spec(bad)
        print("ERROR: this should have failed validation")
    except jsonschema.ValidationError as e:
        print(f"Correctly rejected a tampered spec: {e.message}")
