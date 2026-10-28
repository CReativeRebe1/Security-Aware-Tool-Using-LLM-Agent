"""Per-condition SFT data: training cases -> (chat messages, assistant target) (ARCHITECTURE.md §6).

The same EvidenceMask and prompt renderer as evaluation (P3), and the decoder's skeleton as the target text, so
the model is trained on exactly the format it is scored on. Labels per condition:
  four-way (B5, -prov/-auth/-RAG/-intermediate): gold_decision
  binary (B4):                                   gold_final_action
  three-way (b5_no_ask / b5_no_esc):             removed class -> gold_final_action
`b5_no_inter` drops missing_evidence / required_authority from the target. B4 and B5 see the same examples.
Every case is asserted against pool train_only (train-source minus the dev pool used for the B4 threshold).

  python -m sagate.train.build_sft --condition b5_qlora_4way --cases outputs/sft/train_only_variants.jsonl \
         [annotations/train_nl.jsonl] --out outputs/sft
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Iterable

from ..config import Condition, load_condition, load_config
from ..data.cases import Case, load_cases
from ..data.loaders import AgentDojoData, write_jsonl
from ..data.splits import Splits
from ..evidence.mask import EvidenceMask
from ..gate.prompts import chat_messages, target_text
from ..gate.schema import GateOutput, collapse_decision
from .nl_examples import load_nl_examples

TRAINED = ("b4_qlora_binary", "b5_qlora_4way", "b5_no_prov", "b5_no_auth", "b5_no_rag", "b5_no_ask", "b5_no_esc",
           "b5_no_inter")


def target_for(case: Case, cond: Condition) -> GateOutput:
    if cond.binary:
        decision = case.gold_final_action
    else:
        decision = collapse_decision(case.gold_decision, cond.decision_space, case.gold_final_action)
    return GateOutput(decision=decision, missing_evidence=case.gold_missing_evidence or "none",
                      required_authority=case.gold_required_authority or "none")


def sft_rows(cases: Iterable[Case], cond: Condition, splits: Splits) -> list[dict]:
    if cond.gate_kind != "llm" or not cond.adapter:
        raise ValueError(f"{cond.name} is not a trained condition")
    if cond.provenance == "inferred":
        raise ValueError(f"{cond.name} swaps provenance at test time; it reuses the B5 adapter (§7)")
    mask = EvidenceMask.from_condition(cond)
    rows = []
    for c in cases:
        splits.assert_pool(c, "train_only")
        if not c.has_gold:
            raise ValueError(f"training case {c.case_id} has no gold labels")
        gi = mask.apply(c.input, c.alt_provenance)
        tgt = target_for(c, cond)
        rows.append({
            "case_id": c.case_id, "condition": cond.name,
            "messages": chat_messages(gi, cond.decision_space, cond.intermediate),
            "target": target_text(tgt.target_json(cond.intermediate)),
            "decision": tgt.decision, "subset": c.subset, "round": c.meta.get("round", 0),
        })
    return rows


def load_training_cases(paths: Iterable[str | Path]) -> list[Case]:
    """Variant files are Case JSONL; files under annotations/ named *_nl.jsonl go through the NL validator."""
    out, seen = [], set()
    for p in paths:
        cs = load_nl_examples(p) if Path(p).name.endswith("_nl.jsonl") else load_cases(p)
        for c in cs:
            if c.case_id in seen:
                raise ValueError(f"duplicate training case {c.case_id} ({p})")
            seen.add(c.case_id)
            out.append(c)
    return out


def build(conditions: list[str], case_paths: list[str], out_dir: str | Path, cfg_path: str | None = None) -> dict:
    cfg = load_config(cfg_path)
    splits = Splits(AgentDojoData(cfg.data_dir))
    cases = load_training_cases([p for p in case_paths if Path(p).exists()])
    out_dir = Path(out_dir)
    paths = {}
    for name in conditions:
        cond = load_condition(name)
        rows = sft_rows(cases, cond, splits)
        paths[cond.name] = out_dir / f"{cond.name}.jsonl"
        write_jsonl(paths[cond.name], rows)
        print(f"{cond.name}: {len(rows)} examples -> {paths[cond.name]}  targets {dict(Counter(r['decision'] for r in rows))}")
    return paths


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--condition", nargs="+", default=list(TRAINED), help="default: all 8 trained conditions")
    ap.add_argument("--cases", nargs="+", required=True, help="variant case files (+ annotations/train_nl.jsonl)")
    ap.add_argument("--out", default=None, help="default: <outputs>/sft")
    ap.add_argument("--config", default=None)
    a = ap.parse_args(argv)
    out = a.out or load_config(a.config).outputs_dir / "sft"
    build(a.condition, a.cases, out, a.config)


if __name__ == "__main__":
    main()
