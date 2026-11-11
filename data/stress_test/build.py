"""Stress-test set: specs/*.yaml -> cases.jsonl (gold-labelled, pool "test"), plus a rules-gate baseline.

Cases are built by the same code as the synthetic training cases (sagate.train.synthetic), so the evidence has the
format the gates see. Labels are the author's intended labels from the specs; they are not adjudicated.

  PYTHONPATH=src python data/stress_test/build.py            # write cases.jsonl, print the baseline
  PYTHONPATH=src python data/stress_test/build.py --check    # print only, write nothing
  PYTHONPATH=src python -m sagate.eval.run_gate --condition b5_qlora_4way --cases data/stress_test/cases.jsonl \
         --pool test --adapter-dir <adapters> --out outputs/predictions/stress
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import yaml

from sagate.config import load_config
from sagate.data.cases import Case, save_cases
from sagate.data.loaders import AgentDojoData
from sagate.eval.metrics import final_correct, needs_authorization, unauthorized
from sagate.evidence.context_builder import ContextBuilder
from sagate.evidence.mask import EvidenceMask
from sagate.evidence.policy_rag import parse_handbook
from sagate.gate.guards import GuardedGate
from sagate.gate.rules import RulesGate
from sagate.resolution.loop import resolve
from sagate.resolution.responders import FixedUserResponder, MockApprover, ScenarioResponder
from sagate.train.synthetic import Env, build_realization, load_specs, validate_realization

HERE = Path(__file__).resolve().parent
AUTHOR = "claude-review-2026-11-10"
FOUR_WAY = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")
UNREGISTERED_TOOL_FAMILIES = {"st-bank-tool-outside-registry"}     # the unknown tool is the point of the case


def build_cases(cfg, data) -> list[Case]:
    builder, env, approver = ContextBuilder(cfg, data), Env(data), MockApprover(cfg.resources_dir)
    valid = {c.id for s in ("workspace", "banking") for c in parse_handbook(cfg.resources_dir / "handbooks" / f"{s}.md")}
    reals = load_specs(HERE / "specs")
    errs = [e for r in reals if r.family not in UNREGISTERED_TOOL_FAMILIES for e in validate_realization(r)]
    if errs:
        raise SystemExit("spec problems:\n  " + "\n  ".join(errs))
    cases = []
    for r in reals:
        for b in build_realization(r, builder, env, valid, approver):
            if b.key["round"] != 0:
                continue
            c, k = b.case, b.key
            c.input.case_id = c.input.case_id.replace("syn|", "stress|", 1)
            c.pool = "test"
            c.gold_decision, c.gold_final_action = k["decision"], k["final"]
            c.gold_missing_evidence, c.gold_required_authority = k["missing_evidence"], k["required_authority"]
            c.gold_clause_ids = k["clauses"]
            if k["decision"] == "ASK_USER":
                ok = k["final"] == "ALLOW"
                c.user_response = {"text": r.replies["confirm" if ok else "decline"], "provides": k["missing_evidence"],
                                   "confirmed": ok, "noisy": False}
            c.meta.update(author=AUTHOR, reviewed_by=None, source="stress_test", targets=r.tags, why=r.notes)
            cases.append(c)
    ids = Counter(c.case_id for c in cases)
    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        raise SystemExit(f"duplicate case ids: {dup[:3]}")
    return cases


def baseline(cases: list[Case], cfg, data) -> list[dict]:
    """B1 rules and B1 + guards, with oracle and with inferred provenance, through the resolution loop."""
    user = FixedUserResponder(False, ScenarioResponder(data, 0.15, False, cfg["seed"]))
    approver = MockApprover(cfg.resources_dir)
    gates = {"b1": RulesGate(), "b1_guards": GuardedGate(RulesGate(), FOUR_WAY)}
    rows = []
    for c in cases:
        row = {"case_id": c.case_id, "family": c.meta["family"], "variant": c.meta["variant"],
               "gold": c.gold_decision, "gold_final": c.gold_final_action}
        for prov in ("oracle", "inferred"):
            gi = EvidenceMask(provenance=prov).apply(c.input, c.alt_provenance)
            for name, gate in gates.items():
                p = resolve(c, gi, gate, user, approver, name, cfg["resolution"]["max_rounds"]).to_dict()
                row[f"{name}_{prov}"] = {"first": p["first_decision"], "final": p["final_decision"],
                                         "guard": p["rounds"][0]["output"].get("guard"),
                                         "correct": final_correct(p, c),
                                         "unsafe": needs_authorization(c) and unauthorized(p, c),
                                         "first_ok": p["first_decision"] == c.gold_decision}
        rows.append(row)
    return rows


def run_probes(cfg, data) -> list[dict]:
    builder = ContextBuilder(cfg, data)
    out = []
    for p in yaml.safe_load((HERE / "probes.yaml").read_text()):
        msgs = [{"role": "user", "content": p["prompt"]}]
        try:
            gi, _ = builder.build(p["id"], p["suite"], p["prompt"], p["call"], [], msgs, None)
            gi = EvidenceMask().apply(gi)
            res = {"built": True, "user_may_authorize": gi.authority["user_may_authorize"],
                   "basis": gi.authority["basis"], "b1": RulesGate().decide(gi).decision,
                   "b1_guards": GuardedGate(RulesGate(), FOUR_WAY).decide(gi).decision}
        except Exception as e:                       # the probe is whether this happens
            res = {"built": False, "error": f"{type(e).__name__}: {e}"}
        out.append({"id": p["id"], **res})
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="print the baseline, write nothing")
    a = ap.parse_args(argv)
    cfg = load_config()
    data = AgentDojoData(cfg.data_dir)
    cases = build_cases(cfg, data)
    rows = baseline(cases, cfg, data)
    print(f"{len(cases)} cases, {len({c.meta['family'] for c in cases})} families; gold first decision "
          f"{dict(Counter(c.gold_decision for c in cases))}, final {dict(Counter(c.gold_final_action for c in cases))}")
    for key in ("b1_oracle", "b1_guards_oracle", "b1_inferred", "b1_guards_inferred"):
        print(f"  {key:20s} correct {sum(r[key]['correct'] for r in rows)}/{len(rows)}  "
              f"unsafe {sum(r[key]['unsafe'] for r in rows)}  first-round right {sum(r[key]['first_ok'] for r in rows)}")
    seen = set()
    for r in rows:                                   # one line per family/variant (prompts of a variant agree)
        tag = (r["family"], r["variant"])
        if tag in seen:
            continue
        seen.add(tag)
        cells = "  ".join(f"{k.replace('_oracle', '/o').replace('_inferred', '/i')}="
                          f"{r[k]['first']}>{r[k]['final']}{'' if r[k]['correct'] else ' WRONG'}"
                          f"{' UNSAFE' if r[k]['unsafe'] else ''}{'' if r[k]['first_ok'] else ' first-round-off'}"
                          for k in ("b1_oracle", "b1_guards_oracle", "b1_inferred", "b1_guards_inferred"))
        print(f"{r['family']}/{r['variant']}  gold {r['gold']}>{r['gold_final']}  {cells}")
    for p in run_probes(cfg, data):
        print("probe", json.dumps(p))
    if not a.check:
        n = save_cases(HERE / "cases.jsonl", cases)
        (HERE / "baseline_rules.json").write_text(json.dumps(rows, indent=1) + "\n")
        print(f"wrote {n} cases -> {HERE / 'cases.jsonl'} and baseline_rules.json")


if __name__ == "__main__":
    main()
