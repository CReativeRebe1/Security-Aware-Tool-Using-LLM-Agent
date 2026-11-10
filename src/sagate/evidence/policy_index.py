"""Fact -> clause index for policy retrieval, fused with BM25 in evidence/mask.retrieve_clauses.

Each training case links the facts the gate sees (action, payee/recipient class, sensitivity, provenance trust,
authority basis, earlier rounds) to the clauses its gold label cites. Built from the training split only. An
optional coverage file (generated cases per clause and clause combination, so rare combinations are not missed) is
added at a lower weight: it supplements the labelled cases, it does not replace them.

  python -m sagate.evidence.policy_index --cases annotations/train_human.jsonl [--coverage <file> --coverage-weight 0.3]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from ..config import load_config
from ..data.cases import Case, load_cases
from ..data.splits import LeakageError
from ..gate.schema import GateInput

MIN_SUPPORT = 5          # a fact seen in fewer training cases says nothing reliable
INDEX_FILE = "policy_index.json"


def handbook_hashes() -> dict[str, str]:
    """Fingerprint of each handbook the index was built against; an edited handbook makes the index stale."""
    return {p.stem: hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            for p in sorted((load_config().resources_dir / "handbooks").glob("*.md"))}


def facts(gi: GateInput) -> set[str]:
    """The facts a gate can see; masked evidence contributes nothing, so ablations cannot use it."""
    out = {f"suite={gi.suite}", f"action={gi.proposed_call.get('action')}", f"fn={gi.proposed_call['function']}",
           f"history={gi.resolution_history[0]['kind'] if gi.resolution_history else 'none'}"}
    if gi.authority is not None:
        a = gi.authority
        out |= {f"may_authorize={a.get('user_may_authorize')}", f"role={a.get('required_role')}"}
        out |= {f"basis={b}" for b in a.get("basis", [])}
        out |= {f"party={str(p).split(':')[0]}" for p in a.get("affected_party", [])}
    if gi.sensitivity is not None:
        out |= {f"resource={gi.sensitivity.get('resource')}", f"flow={gi.sensitivity.get('flow')}"}
    if gi.provenance is not None:
        call = next((r for r in gi.provenance if r.get("kind") == "call"), {})
        out.add(f"call_trust={call.get('trust')}")
        out |= {f"arg_trust={r.get('trust')}" for r in gi.provenance if r.get("kind") == "arg"}
    return out


def build(cases: list[Case], coverage: list[Case] = (), coverage_weight: float = 0.3) -> dict:
    bad = [c.case_id for c in cases if c.pool != "train"]
    if bad:
        raise LeakageError(f"the index is built from training cases only; got {bad[:3]}")
    links: dict[str, Counter] = defaultdict(Counter)
    support: Counter = Counter()
    for weight, group in ((1.0, cases), (coverage_weight, coverage)):
        for c in group:
            if not c.gold_clause_ids:
                continue
            for f in facts(c.input):
                support[f] += weight
                for clause in c.gold_clause_ids:
                    links[f][clause] += weight
    return {"min_support": MIN_SUPPORT, "handbooks": handbook_hashes(), "support": dict(support),
            "links": {f: dict(v) for f, v in links.items()}}


@lru_cache(maxsize=None)
def load_index() -> dict | None:
    path = load_config().resources_dir / INDEX_FILE
    return json.loads(path.read_text()) if path.exists() else None


@lru_cache(maxsize=None)
def _usable(suite: str) -> bool:
    index = load_index()
    if index is None:
        return False
    if index.get("handbooks", {}).get(suite) != handbook_hashes().get(suite):
        warnings.warn(f"policy index is stale for '{suite}' (handbook changed since it was built): using BM25 only. "
                      "Rebuild with python -m sagate.evidence.policy_index")
        return False
    return True


def rank(gi: GateInput) -> list[str]:
    """Clause ids for this call's facts, best first. Empty, so retrieval falls back to BM25, when no index exists
    or the handbook changed since it was built."""
    if not _usable(gi.suite):
        return []
    index = load_index()
    score: Counter = Counter()
    for f in facts(gi):
        n = index["support"].get(f, 0)
        if n >= index["min_support"]:
            for clause, k in index["links"].get(f, {}).items():
                score[clause] += k / n
    prefix = {"banking": "BANK-", "workspace": "WS-"}.get(gi.suite, "")
    return [c for c, _ in score.most_common() if c.startswith(prefix)]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", required=True, help="training cases with gold clause ids")
    ap.add_argument("--coverage", default=None, help="generated per-clause coverage cases (optional)")
    ap.add_argument("--coverage-weight", type=float, default=0.3)
    ap.add_argument("--out", default=None, help=f"default: <resources>/{INDEX_FILE}")
    a = ap.parse_args(argv)
    coverage = load_cases(a.coverage) if a.coverage else []
    index = build(load_cases(a.cases), coverage, a.coverage_weight)
    out = Path(a.out) if a.out else load_config().resources_dir / INDEX_FILE
    out.write_text(json.dumps(index, indent=1, sort_keys=True))
    print(f"{len(index['links'])} facts, {len({c for v in index['links'].values() for c in v})} clauses -> {out}")


if __name__ == "__main__":
    main()
