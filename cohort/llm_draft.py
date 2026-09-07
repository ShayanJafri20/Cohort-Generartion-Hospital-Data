"""
The only piece of this pipeline that talks to an LLM, and the only thing it's
allowed to produce is a CohortSpec — never SQL, never a database connection.
Everything it returns still goes through validate_spec.py before anything
downstream trusts it (proven in validate_spec.py's own self-test, which
rejects a tampered spec containing a SQL injection attempt).

Uses Gemini (free tier, via Google AI Studio — no billing account needed):
pip install google-genai, then set GEMINI_API_KEY in .env. Without a key,
this prints what it *would* have sent and falls back to example_spec.json,
so the rest of the pipeline still runs end-to-end without one.

Free-tier note, and why it doesn't matter here: Google may use free-tier
inputs to improve their models. This call only ever sends the protocol text
and the JSON Schema — never a database connection, never a patient row — so
that's a non-issue for the exact reason Chapter 03's AI/PHI boundary exists:
the AI's blast radius is capped by what it's structurally allowed to see.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cohort.validate_spec import validate_spec, load_schema  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL = "gemini-3.6-flash"  # per the API itself: 2.5-flash is deprecated for new users

SYSTEM_PROMPT = """You turn a short clinical trial eligibility description into a CohortSpec
JSON object that strictly matches the given JSON Schema. Only use the enum values the
schema allows — if the protocol asks for something the schema can't express, pick the
closest supported option, never invent new fields."""


def draft_spec(protocol_text: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    schema = load_schema()

    if not api_key:
        print("No GEMINI_API_KEY set — skipping the real LLM call for this demo run.")
        print("What would be sent to the model:")
        print(f"  model: {MODEL}")
        print(f"  system: {SYSTEM_PROMPT[:80]}...")
        print(f"  schema: cohort_spec.schema.json ({len(json.dumps(schema))} bytes)")
        print(f"  protocol text: {protocol_text!r}")
        fallback = json.loads((Path(__file__).resolve().parent / "example_spec.json").read_text())
        print("\nFalling back to example_spec.json so the rest of the pipeline still runs.")
        return validate_spec(fallback)

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=f"{SYSTEM_PROMPT}\n\nProtocol:\n{protocol_text}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0,  # deterministic-as-possible schema adherence
        ),
    )
    spec = json.loads(response.text)
    return validate_spec(spec)  # the AI drafted it; the schema still has final say


if __name__ == "__main__":
    example_protocol = (
        "Inclusion: age 40 or older, diagnosed with Type 2 diabetes, HbA1c above 7%, "
        "currently on Metformin. Exclusion: severe (end-stage) renal disease, pregnancy."
    )
    spec = draft_spec(example_protocol)
    print("\nDrafted + validated CohortSpec:")
    print(json.dumps(spec, indent=2))
