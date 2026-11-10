"""Retrieval experiment 2: BM25 + evidence words + a fact-to-clause index, on the frozen human-labelled splits.

  git show origin/HumanLabelDataset:human_label_dataset/splits/train.jsonl > /tmp/train.jsonl   # and dev.jsonl
  python experiments/rag/run_index_exp.py --train /tmp/train.jsonl --dev /tmp/dev.jsonl [--generated <variants.jsonl>]

The index links facts the gate sees (action, payee/recipient class, sensitivity, provenance trust, authority basis,
earlier rounds) to the clauses gold labels cite. It is built from the training split only and scored on dev; the
test split is not used. The method chosen here is implemented in branch valhalla (sagate.evidence.policy_index and
sagate.evidence.mask.retrieve_clauses).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from sagate.evidence.policy_rag import BM25, build_query, parse_handbook, tokenize  # noqa: E402

MIN_SUPPORT = 5


def rows(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def evidence_words(inp: dict) -> str:
    prov = inp.get("provenance") or []
    words = []
    call = next((p for p in prov if p.get("kind") == "call"), {})
    if call.get("trust") == "untrusted":
        words.append("action caused by an instruction inside tool output content document message not the user")
    args = [p for p in prov if p.get("kind") == "arg"]
    if any(p.get("trust") == "untrusted" for p in args):
        words.append("arguments copied from untrusted content instruction")
    elif any(p.get("trust") == "third_party" for p in args):
        words.append("recipient payee details taken from content document email confirm")
    if inp.get("resolution_history"):
        words.append("clarification approval round answer limits on resolution")
    return " ".join(words)


def facts(inp: dict) -> set[str]:
    a, s, p = inp.get("authority") or {}, inp.get("sensitivity") or {}, inp.get("provenance") or []
    hist = inp.get("resolution_history") or []
    call = next((r for r in p if r.get("kind") == "call"), {})
    out = {f"suite={inp['suite']}", f"action={inp['proposed_call'].get('action')}",
           f"fn={inp['proposed_call']['function']}", f"history={hist[0]['kind'] if hist else 'none'}",
           f"may_authorize={a.get('user_may_authorize')}", f"role={a.get('required_role')}",
           f"resource={s.get('resource')}", f"flow={s.get('flow')}", f"call_trust={call.get('trust')}"}
    out |= {f"basis={b}" for b in a.get("basis", [])}
    out |= {f"party={str(x).split(':')[0]}" for x in a.get("affected_party", [])}
    out |= {f"arg_trust={r.get('trust')}" for r in p if r.get("kind") == "arg"}
    return out


def build_index(cases: list[dict]) -> tuple[dict, Counter]:
    links, support = defaultdict(Counter), Counter()
    for r in cases:
        if r.get("gold_clause_ids"):
            for f in facts(r["input"]):
                support[f] += 1
                for c in r["gold_clause_ids"]:
                    links[f][c] += 1
    return links, support


def index_rank(inp: dict, links: dict, support: Counter) -> list[str]:
    score = Counter()
    for f in facts(inp):
        if support[f] >= MIN_SUPPORT:
            for c, n in links[f].items():
                score[c] += n / support[f]
    prefix = {"banking": "BANK-", "workspace": "WS-"}[inp["suite"]]
    return [c for c, _ in score.most_common() if c.startswith(prefix)]


class Retriever:
    def __init__(self, suite: str):
        self.clauses = parse_handbook(ROOT / "resources" / "handbooks" / f"{suite}.md")
        self.index = BM25([tokenize(f"{c.title} {c.title} {c.text}") for c in self.clauses])

    def rank(self, query: str) -> list[str]:
        s = self.index.scores(tokenize(query))
        return [self.clauses[i].id for i in sorted(range(len(s)), key=lambda i: (-s[i], i))]


def evaluate(dev: list[dict], method, k: int) -> tuple[float, int, int]:
    rec, allin, n = 0.0, 0, 0
    for r in dev:
        if not r.get("gold_clause_ids"):
            continue
        gold, top = set(r["gold_clause_ids"]), set(method(r["input"])[:k])
        rec += len(gold & top) / len(gold)
        allin += gold <= top
        n += 1
    return rec / n, allin, n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--train", required=True)
    ap.add_argument("--dev", required=True)
    ap.add_argument("--generated", default=None, help="rule-labelled generated cases, to test an index built without humans")
    ap.add_argument("--out", default=str(ROOT / "experiments/rag/results/index_results.json"))
    a = ap.parse_args()
    train, dev = rows(a.train), rows(a.dev)
    ret = {s: Retriever(s) for s in ("banking", "workspace")}

    def query(inp, evidence):
        c = inp["proposed_call"]
        q = build_query(inp["user"].get("prompt") or "", c["function"], c.get("action") or "", inp.get("authority"),
                        inp.get("sensitivity"))
        return q + " " + evidence_words(inp) if evidence else q

    def fused(links, support):
        def method(inp):
            score = Counter()
            for ranking in (ret[inp["suite"]].rank(query(inp, True)), index_rank(inp, links, support)):
                for i, c in enumerate(ranking):
                    score[c] += 1 / (10 + i)
            return [c for c, _ in score.most_common()]
        return method

    links, support = build_index(train)
    methods = {
        "BM25 trusted query (previous)": lambda inp: ret[inp["suite"]].rank(query(inp, False)),
        "BM25 + evidence words": lambda inp: ret[inp["suite"]].rank(query(inp, True)),
        "Fact index alone (train labels)": lambda inp: index_rank(inp, links, support),
        "BM25 + evidence + fact index (chosen)": fused(links, support),
    }
    if a.generated:
        g_links, g_support = build_index(rows(a.generated))
        methods["BM25 + evidence + index from generated cases only"] = fused(g_links, g_support)
    results = {}
    print(f"dev: {sum(bool(r.get('gold_clause_ids')) for r in dev)} cases with gold clauses")
    for name, method in methods.items():
        results[name] = {}
        for k in (3, 5, 8):
            rec, allin, n = evaluate(dev, method, k)
            results[name][f"recall@{k}"] = round(rec, 3)
            results[name][f"all_gold_in_top{k}"] = f"{allin}/{n}"
        print(f"{name:52s} " + "  ".join(f"R@{k} {results[name][f'recall@{k}']:.3f}" for k in (3, 5, 8)))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
