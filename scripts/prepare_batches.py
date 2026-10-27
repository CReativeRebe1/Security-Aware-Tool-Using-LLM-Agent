"""Shuffle synthetic data and partition into batches of 100 for human labelling.

Creates:
- data/synthetic_data/batches/batch_XX.jsonl
- data/synthetic_data/batches/batch_XX.json
- data/synthetic_data/batches/batch_XX_to_label.csv
- data/synthetic_data/batches/manifest.json
- data/synthetic_data/shuffled_index.json
"""

import csv
import json
import random
import sys
from collections import Counter
from pathlib import Path

# Add src to python path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sagate.data.cases import load_cases, save_cases
from sagate.gate.prompts import render_input

LABEL_COLUMNS = [
    "gold_decision",
    "gold_final_action",
    "gold_missing_evidence",
    "gold_required_authority",
    "gold_clause_ids",
    "user_response_text",
    "user_response_confirmed",
    "user_response_noisy_text",
    "user_response_noisy_confirmed",
    "notes",
]


def prepare_batches(
    cases_file: str = "data/synthetic_data/cases.jsonl",
    to_label_file: str = "data/synthetic_data/to_label.csv",
    output_dir: str = "data/synthetic_data/batches",
    batch_size: int = 100,
    seed: int = 42,
):
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"Loading cases from {cases_file}...")
    cases = load_cases(cases_file)
    print(f"Loaded {len(cases)} cases.")

    # Also load the raw json lines and csv rows to preserve any exact fields
    with open(cases_file, "r", encoding="utf-8") as f:
        raw_json_lines = [json.loads(line) for line in f]

    csv_rows_by_id = {}
    if Path(to_label_file).exists():
        with open(to_label_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            csv_rows_by_id = {row["case_id"]: row for row in reader}

    # Generate shuffled indices with fixed seed
    rng = random.Random(seed)
    indices = list(range(len(cases)))
    rng.shuffle(indices)

    # Save the permutation mapping
    with open(out_path / "shuffled_index.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "seed": seed,
                "total_cases": len(cases),
                "indices": indices,
                "case_ids": [cases[i].case_id for i in indices],
            },
            f,
            indent=2,
        )

    shuffled_cases = [cases[i] for i in indices]
    shuffled_raw_json = [raw_json_lines[i] for i in indices]

    num_batches = (len(shuffled_cases) + batch_size - 1) // batch_size
    manifest = {
        "seed": seed,
        "total_cases": len(shuffled_cases),
        "batch_size": batch_size,
        "total_batches": num_batches,
        "batches": [],
    }

    for b in range(num_batches):
        start_idx = b * batch_size
        end_idx = min(start_idx + batch_size, len(shuffled_cases))
        batch_cases = shuffled_cases[start_idx:end_idx]
        batch_raw_json = shuffled_raw_json[start_idx:end_idx]

        batch_id = f"batch_{b + 1:02d}"
        batch_num = b + 1

        # File paths
        jsonl_filename = f"{batch_id}.jsonl"
        json_filename = f"{batch_id}.json"
        csv_filename = f"{batch_id}_to_label.csv"

        jsonl_path = out_path / jsonl_filename
        json_path = out_path / json_filename
        csv_path = out_path / csv_filename

        # 1. Save JSONL (valid sagate Case objects)
        save_cases(str(jsonl_path), batch_cases)

        # 2. Save enriched JSON (for web UI)
        enriched_cases = []
        for idx, (c, raw) in enumerate(zip(batch_cases, batch_raw_json)):
            # Rendered text
            case_text = render_input(c.input)
            item = {
                "batch_id": batch_id,
                "batch_index": idx,
                "global_index": start_idx + idx,
                "case_id": c.case_id,
                "suite": c.input.suite,
                "category": c.category,
                "subset": c.subset,
                "difficulty": c.meta.get("difficulty") if hasattr(c, "meta") and isinstance(c.meta, dict) else "medium",
                "family": c.meta.get("family") if hasattr(c, "meta") and isinstance(c.meta, dict) else "",
                "round": c.meta.get("round", 0) if hasattr(c, "meta") and isinstance(c.meta, dict) else 0,
                "case_text": case_text,
                "raw_case": raw,
            }
            enriched_cases.append(item)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(enriched_cases, f, indent=2)

        # 3. Save CSV (compatible with sagate.data.annotation export / agreement / gold)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["case_id", "suite", "category", "subset", "case_text", *LABEL_COLUMNS])
            for c in batch_cases:
                orig_csv = csv_rows_by_id.get(c.case_id, {})
                case_text = orig_csv.get("case_text") or render_input(c.input)
                writer.writerow([
                    c.case_id,
                    c.input.suite,
                    c.category,
                    c.subset,
                    case_text,
                    *[""] * len(LABEL_COLUMNS),
                ])

        # Batch statistics
        suites = Counter(c.input.suite for c in batch_cases)
        categories = Counter(c.category for c in batch_cases)
        difficulties = Counter(
            c.meta.get("difficulty", "medium") if hasattr(c, "meta") and isinstance(c.meta, dict) else "medium"
            for c in batch_cases
        )

        manifest["batches"].append({
            "batch_id": batch_id,
            "batch_num": batch_num,
            "case_count": len(batch_cases),
            "start_index": start_idx,
            "end_index": end_idx,
            "files": {
                "json": f"batches/{json_filename}",
                "jsonl": f"batches/{jsonl_filename}",
                "csv": f"batches/{csv_filename}",
            },
            "stats": {
                "suites": dict(suites),
                "categories": dict(categories),
                "difficulties": dict(difficulties),
            },
        })

        print(f"Generated {batch_id}: {len(batch_cases)} cases ({jsonl_filename}, {csv_filename})")

    manifest_path = out_path / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nManifest written to {manifest_path}")
    print(f"Successfully divided 2,000 cases into {num_batches} batches of {batch_size}!")


if __name__ == "__main__":
    prepare_batches()
