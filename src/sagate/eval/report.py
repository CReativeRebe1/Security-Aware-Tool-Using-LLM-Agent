"""Print metrics for prediction files (raw counts + %). Without gold labels, prints the decision mix only.

  python -m sagate.eval.report --cases outputs/cases/test.jsonl --pred outputs/predictions/b1_rules.jsonl ...
  python -m sagate.eval.report ... --gold annotations/gold.jsonl --compare b3_prompt_4way b2_prompt_binary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..data.cases import attach_gold, load_cases
from ..data.loaders import read_jsonl
from .metrics import Rate, compute, decision_mix, noise_induced_errors, per_case_success
from .stats import mcnemar_exact, paired_bootstrap

_ORDER = ["final_resolution_success", "unauthorized_action_rate", "unnecessary_deferral_rate", "raw_deferral_rate",
          "gold_deferral_prevalence", "mean_interactions", "first_round_accuracy", "clarification_success",
          "escalation_precision", "escalation_recall", "over_blocking_rate", "defaulted_to_block",
          "binary_success", "binary_unauthorized_rate", "authority_spoofing_success", "macro_f1_missing_evidence", "macro_f1_required_authority",
          "recall@3", "recall@5", "provenance_attribution_accuracy", "instruction_origin_accuracy"]


def load_preds(paths: list[str]) -> dict[str, list[dict]]:
    """condition name (file stem without .shardN) -> predictions; shards are merged."""
    out: dict[str, list[dict]] = {}
    for p in paths:
        name = Path(p).name.removesuffix(".jsonl").split(".shard")[0]
        out.setdefault(name, []).extend(read_jsonl(p))
    return out


def _fmt(v) -> str:
    if isinstance(v, Rate):
        return str(v)
    if isinstance(v, float):
        return f"{v:.3f}"
    return "—" if v is None else str(v)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--pred", nargs="+", required=True)
    ap.add_argument("--gold", default=None, help="JSONL of adjudicated gold rows keyed by case_id")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), help="paired bootstrap + McNemar on success")
    ap.add_argument("--json", default=None, help="also write metrics as JSON")
    a = ap.parse_args(argv)

    cases = load_cases(a.cases)
    if a.gold:
        print(f"gold attached to {attach_gold(cases, read_jsonl(a.gold))}/{len(cases)} cases")
    preds = load_preds(a.pred)
    if a.compare:
        missing = [x for x in a.compare if x not in preds]
        if missing:
            raise SystemExit(f"--compare: no predictions named {missing}; have {sorted(preds)}")
    have_gold = any(c.has_gold for c in cases)
    results = {}
    for name, ps in preds.items():
        if not have_gold:
            results[name] = decision_mix(ps)
            print(f"\n== {name} (no gold labels: decision mix)\n{json.dumps(results[name], indent=1)}")
            continue
        m = compute(ps, cases)
        results[name] = m
        print(f"\n== {name}  (n={m['n']})")
        for k in _ORDER:
            if k in m:
                print(f"  {k:30s} {_fmt(m[k])}")
        for s, sm in m.get("by_subset", {}).items():
            print(f"  [{s}] success {sm['final_resolution_success']}  unauthorized {sm['unauthorized_action_rate']}")
        clean = name.replace("_noisy", "", 1)
        if clean != name and clean in preds:
            m["noise_induced_error_rate"] = noise_induced_errors(preds[clean], ps, cases)
            print(f"  {'noise_induced_error_rate':30s} {_fmt(m['noise_induced_error_rate'])}  (vs {clean})")
    if a.compare and have_gold:
        sa, sb = (per_case_success(preds[x], cases) for x in a.compare)
        keys = sorted(set(sa) & set(sb))
        bs = paired_bootstrap([sa[k] for k in keys], [sb[k] for k in keys])
        mc = mcnemar_exact([sa[k] for k in keys], [sb[k] for k in keys])
        print(f"\n{a.compare[0]} - {a.compare[1]} success: diff {bs['diff']:+.3f} "
              f"[{bs['ci_low']:+.3f}, {bs['ci_high']:+.3f}] (n={bs['n']}), McNemar p={mc['p_value']:.4f}")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1, default=str))


if __name__ == "__main__":
    main()
