"""
Downloads the CMS DE-SynPUF dataset, already in OMOP CDM v5.4 shape, from
AWS Open Data (public, no account/credentials needed — verified via
`curl https://synpuf-omop.s3.amazonaws.com/?list-type=2`).

Source: https://registry.opendata.aws/cmsdesynpuf-omop/
Bucket: s3://synpuf-omop/  (us-east-1)
"""
import sys
from pathlib import Path

import requests

BUCKET_URL = "https://synpuf-omop.s3.amazonaws.com"

# The clinical data tables SynPUF ships (NOT the vocabulary tables —
# concept/vocabulary/concept_relationship/etc. are loaded separately from
# the real OHDSI Athena vocabulary, per the workbook's vocabulary chapter).
TABLES = [
    "care_site", "condition_era", "condition_occurrence", "death",
    "device_exposure", "drug_era", "drug_exposure", "drug_strength",
    "location", "measurement", "observation", "observation_period",
    "payer_plan_period", "person", "procedure_occurrence", "provider",
    "visit_occurrence",
]

DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


def download_table(size_folder: str, table: str, dest_dir: Path):
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{table}.csv.gz"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  {table:22s} already downloaded ({dest.stat().st_size:,} bytes)")
        return dest

    url = f"{BUCKET_URL}/{size_folder}/{table}.csv.gz"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        written = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                written += len(chunk)
        print(f"  {table:22s} downloaded ({written:,} bytes)")
    return dest


def download_all(size: str = "100k"):
    size_folder = {"1k": "cmsdesynpuf1k", "100k": "cmsdesynpuf100k", "2.3m": "cmsdesynpuf2.3"}[size]
    dest_dir = DATA_ROOT / f"synpuf_{size}"
    print(f"Downloading SynPUF ({size}) into {dest_dir}")
    for table in TABLES:
        download_table(size_folder, table, dest_dir)
    print("Done.")
    return dest_dir


if __name__ == "__main__":
    size_arg = sys.argv[1] if len(sys.argv) > 1 else "100k"
    download_all(size_arg)
