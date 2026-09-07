"""
Deterministic, and only this: a validated CohortSpec in, a parameterized SQL
query out. Every value here already passed jsonschema's enum/range checks in
validate_spec.py, so string concatenation is safe — there is no free-text
field anywhere in a CohortSpec for an injection to hide in.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cohort.validate_spec import validate_spec  # noqa: E402

_OPERATOR_SQL = {">": ">", "<": "<", ">=": ">=", "<=": "<="}  # closed set, re-checked below


def compile_to_sql(spec: dict) -> str:
    validate_spec(spec)  # never trust a caller that skipped validation

    inc = spec["inclusion"]
    min_age = int(inc["min_age"])
    operator = _OPERATOR_SQL[inc["measurement"]["operator"]]
    threshold = float(inc["measurement"]["value"])

    where = [
        f"age >= {min_age}",
        "has_t2d",
        f"latest_hba1c_value {operator} {threshold}",
        "on_metformin",
    ]
    if "esrd" in spec["exclusion"]:
        where.append("not has_esrd")
    if "pregnancy" in spec["exclusion"]:
        where.append("not is_pregnant")

    where_sql = "\n  and ".join(where)
    return (
        "select person_id, age, latest_hba1c_value, metformin_start_date, "
        "t2d_onset_date\n"
        "from marts.diabetes_mart\n"
        f"where {where_sql}\n"
        "order by person_id;"
    )


if __name__ == "__main__":
    import json

    spec = json.loads((Path(__file__).resolve().parent / "example_spec.json").read_text())
    print(compile_to_sql(spec))
