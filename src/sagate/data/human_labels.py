"""Frozen human-labelled cases (branch HumanLabelDataset, human_label_dataset/splits) -> the pipeline's case files.

  python -m sagate.data.human_labels --splits human_label_dataset/splits --out annotations

Writes annotations/train_human.jsonl (NB03 training), annotations/dev_cases.jsonl (B4 threshold, NB02/NB04 dev) and
annotations/test_cases.jsonl (the reportable test set). Labels are copied unchanged; only pipeline fields are added:
subset, round and family in meta, top-5 retrieved clause ids (Recall@5), inferred provenance rebuilt from the case's
own tool outputs, and the seeded 15% noisy share of fixed user replies.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ..evidence.mask import retrieve_clauses
from ..evidence.provenance import ToolBlock, build_records
from ..gate.schema import GateInput
from .annotation import NOISE_RATE, _noisy
from .cases import Case, save_cases
from .loaders import read_jsonl

FILES = {"train": "train_human.jsonl", "dev": "dev_cases.jsonl", "test": "test_cases.jsonl"}


def _blocks(gi: dict) -> list[ToolBlock]:
    out = []
    for t in gi.get("untrusted_content") or []:
        function, index = t["source"].split(":", 1)[1].rsplit("#", 1)
        out.append(ToolBlock(id=t["id"], function=function, call_index=int(index), text=t["text"], third_party=True))
    return out


def convert(row: dict, seed: int = 42) -> Case:
    gi = row["input"]
    call = gi["proposed_call"]
    retrieved = [c["id"] for c in retrieve_clauses(GateInput.from_dict(gi))]   # what the full gate is shown
    inferred = build_records(call.get("args") or {}, gi["user"].get("prompt") or "", _blocks(gi), mode="inferred")
    reply = row.get("user_response")
    if reply:
        noisy = _noisy(row["case_id"], seed, NOISE_RATE) and bool(reply.get("noisy_text"))
        reply = {**reply, "provides": row.get("gold_missing_evidence"), "noisy": noisy, "noisy_provides": "none"}
    meta = {"round": row.get("round", 0), "family": row["family"], "variant": row.get("variant"), "tier": row.get("tier"),
            "template": row["family"], "retrieved_ids": retrieved, "source": "HumanLabelDataset"}
    return Case.from_dict({**row, "subset": "decision_only", "scenario_id": None, "meta": meta,
                           "alt_provenance": {"inferred": inferred}, "user_response": reply})


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--splits", default="human_label_dataset/splits")
    ap.add_argument("--out", default="annotations")
    a = ap.parse_args(argv)
    families = {}
    for pool, name in FILES.items():
        cases = [convert(r) for r in read_jsonl(Path(a.splits) / f"{pool}.jsonl")]
        bad = [c.case_id for c in cases if c.pool != pool]
        if bad:
            raise SystemExit(f"{pool}: {len(bad)} cases tagged with another pool, e.g. {bad[0]}")
        families[pool] = {c.meta["family"] for c in cases}
        n = save_cases(Path(a.out) / name, cases)
        print(f"{pool}: {n} cases -> {Path(a.out) / name}  gold {dict(Counter(c.gold_decision for c in cases))}")
    for x, y in (("train", "dev"), ("train", "test"), ("dev", "test")):
        if families[x] & families[y]:
            raise SystemExit(f"families shared by {x} and {y}: {sorted(families[x] & families[y])[:3]}")


if __name__ == "__main__":
    main()
