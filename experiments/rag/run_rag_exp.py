#!/usr/bin/env python3
"""Policy-retrieval experiment: which retriever puts the right handbook clauses in front of the gate?

    python experiments/rag/run_rag_exp.py            # writes experiments/rag/results/ (+ charts)

Data
  dev  : data/labled-data/synthetic_nl.jsonl   2,000 synthetic cases (pool train) -> choose the method here
  test : annotations/test_cases.jsonl          160 frozen AgentDojo test cases (pool test) -> confirm only
  Each case has gold_clause_ids. The candidate clauses are the suite's handbook (resources/handbooks/<suite>.md).

Queries (built only from what the gate already sees, never from gold labels)
  trusted   the current query (sagate.evidence.policy_rag.build_query): user prompt, tool, action, authority and
            sensitivity facts. It deliberately leaves out provenance.
  evidence  trusted + a few words describing the evidence the gate already has: untrusted origin of the call or
            of arguments, arguments copied from content, earlier clarification/approval rounds.

Methods
  BM25 (the current retriever) | dense bi-encoders | hybrid BM25+dense (reciprocal rank fusion) |
  hybrid + cross-encoder re-ranking | evidence rules (force the clause an evidence fact points to) + ranker.
Metrics: Recall@k (share of gold clauses in the top k), Hit@3 (at least one), All@3 (all gold in the top 3), MRR,
"key clause" Recall@3 on injected-origin cases (is X-5.1 shown?), latency per query.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

from sagate.evidence.policy_rag import BM25, build_query, parse_handbook, tokenize  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
K_MAX = 10
SEED = 0

DENSE = {  # name -> (hf id, pooling, query prefix, passage prefix)
    "MiniLM-L6": ("sentence-transformers/all-MiniLM-L6-v2", "mean", "", ""),
    "e5-small": ("intfloat/e5-small-v2", "mean", "query: ", "passage: "),
    "bge-small": ("BAAI/bge-small-en-v1.5", "cls", "Represent this sentence for searching relevant passages: ", ""),
    "bge-base": ("BAAI/bge-base-en-v1.5", "cls", "Represent this sentence for searching relevant passages: ", ""),
}
RERANKERS = {
    "msmarco-MiniLM": "cross-encoder/ms-marco-MiniLM-L-6-v2",
    "bge-reranker": "BAAI/bge-reranker-base",
}


# ----------------------------------------------------------------------------------------------- data
def load_cases(path: Path, split: str) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        c = json.loads(line)
        gold = [g for g in (c.get("gold_clause_ids") or []) if g]
        if not gold:
            continue
        inp = c["input"]
        out.append({"id": inp["case_id"], "split": split, "suite": inp["suite"], "category": c.get("category"),
                    "gold": gold, "input": inp,
                    "shown": [p["id"] for p in inp.get("policy_clauses", [])]})
    return out


def evidence_words(inp: dict) -> str:
    """Plain words for evidence facts the gate already receives (provenance, history), to steer the query."""
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


def queries(c: dict) -> dict:
    inp = c["input"]
    call = inp["proposed_call"]
    q = build_query(inp["user"]["prompt"], call["function"], call.get("action", ""), inp.get("authority"),
                    inp.get("sensitivity"))
    return {"trusted": q, "evidence": (q + " " + evidence_words(inp)).strip()}


RULE_MIN_PRECISION = 0.8      # a rule is used only if its clause is gold this often on dev
ACTIVE_RULES: set[str] | None = None   # filled from dev in main(); None = all rules (used to measure them)


def rule_clauses(c: dict) -> list[str]:
    """Clauses an evidence fact points to directly (no gold used). Ordered by how specific the fact is."""
    inp, pre = c["input"], ("BANK" if c["suite"] == "banking" else "WS")
    prov = inp.get("provenance") or []
    call = next((p for p in prov if p.get("kind") == "call"), {})
    out = []
    if call.get("trust") == "untrusted" or any(p.get("trust") == "untrusted" for p in prov if p.get("kind") == "arg"):
        out.append(f"{pre}-5.1")
    if inp.get("resolution_history"):
        out.append(f"{pre}-6.3")
    a = inp.get("authority") or {}
    if a.get("user_may_authorize") is False and a.get("required_role") not in (None, "none", "current_user"):
        out.append(f"{pre}-6.2")
    if ACTIVE_RULES is not None:
        out = [x for x in out if x.split("-", 1)[1] in ACTIVE_RULES]
    return out


# ----------------------------------------------------------------------------------------------- models
class Dense:
    def __init__(self, hf_id: str, pooling: str, qp: str, pp: str):
        self.tok = AutoTokenizer.from_pretrained(hf_id)
        self.model = AutoModel.from_pretrained(hf_id).to(DEVICE).eval()
        self.pooling, self.qp, self.pp = pooling, qp, pp

    @torch.no_grad()
    def encode(self, texts: list[str], prefix: str) -> np.ndarray:
        vecs = []
        for i in range(0, len(texts), 64):
            batch = self.tok([prefix + t for t in texts[i:i + 64]], padding=True, truncation=True, max_length=512,
                             return_tensors="pt").to(DEVICE)
            h = self.model(**batch).last_hidden_state
            if self.pooling == "cls":
                v = h[:, 0]
            else:
                m = batch["attention_mask"].unsqueeze(-1).float()
                v = (h * m).sum(1) / m.sum(1)
            vecs.append(torch.nn.functional.normalize(v, dim=-1).cpu().numpy())
        return np.concatenate(vecs)


class Reranker:
    def __init__(self, hf_id: str):
        self.tok = AutoTokenizer.from_pretrained(hf_id)
        self.model = AutoModelForSequenceClassification.from_pretrained(hf_id).to(DEVICE).eval()

    @torch.no_grad()
    def scores(self, query: str, docs: list[str]) -> np.ndarray:
        b = self.tok([query] * len(docs), docs, padding=True, truncation=True, max_length=512, return_tensors="pt").to(DEVICE)
        return self.model(**b).logits[:, 0].float().cpu().numpy()


def rrf(rankings: list[list[int]], k: int = 60) -> list[int]:
    s = defaultdict(float)
    for r in rankings:
        for pos, i in enumerate(r):
            s[i] += 1 / (k + pos + 1)
    return sorted(s, key=lambda i: -s[i])


def force_first(forced: list[str], ranked: list[str]) -> list[str]:
    return forced + [x for x in ranked if x not in forced]


# ----------------------------------------------------------------------------------------------- metrics
def metrics(rows: list[dict]) -> dict:
    def rec(r, k):
        return len(set(r["ranked"][:k]) & set(r["gold"])) / len(set(r["gold"]))
    n = len(rows)
    out = {f"R@{k}": sum(rec(r, k) for r in rows) / n for k in (1, 3, 5)}
    out["Hit@3"] = sum(bool(set(r["ranked"][:3]) & set(r["gold"])) for r in rows) / n
    out["All@3"] = sum(set(r["gold"]) <= set(r["ranked"][:3]) for r in rows) / n
    out["MRR"] = sum(next((1 / (i + 1) for i, x in enumerate(r["ranked"]) if x in r["gold"]), 0) for r in rows) / n
    key = [r for r in rows if any(g.endswith("-5.1") for g in r["gold"])]
    out["key5.1@3"] = (sum(any(x.endswith("-5.1") for x in r["ranked"][:3]) for r in key) / len(key)) if key else None
    out["n"] = n
    out["curve"] = [sum(rec(r, k) for r in rows) / n for k in range(1, K_MAX + 1)]
    return out


def bootstrap_ci(rows: list[dict], k: int = 3, b: int = 2000) -> tuple[float, float]:
    rng = random.Random(SEED)
    vals = [len(set(r["ranked"][:k]) & set(r["gold"])) / len(set(r["gold"])) for r in rows]
    means = sorted(sum(rng.choice(vals) for _ in vals) / len(vals) for _ in range(b))
    return means[int(0.025 * b)], means[int(0.975 * b)]


# ----------------------------------------------------------------------------------------------- main
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    handbooks = {s: parse_handbook(ROOT / "resources" / "handbooks" / f"{s}.md") for s in ("banking", "workspace")}
    ids = {s: [c.id for c in cl] for s, cl in handbooks.items()}
    doc_text = {s: [f"{c.title}. {c.text}" for c in cl] for s, cl in handbooks.items()}
    bm25 = {s: BM25([tokenize(f"{c.title} {c.title} {c.text}") for c in cl]) for s, cl in handbooks.items()}

    cases = load_cases(ROOT / "data" / "labled-data" / "synthetic_nl.jsonl", "dev") + \
        load_cases(ROOT / "annotations" / "test_cases.jsonl", "test")
    for c in cases:
        c["q"] = queries(c)
    print(f"cases: dev={sum(c['split'] == 'dev' for c in cases)} test={sum(c['split'] == 'test' for c in cases)}")

    # sanity: our BM25 on the trusted query reproduces the clauses stored in the cases
    def bm25_rank(c, qname):
        s = bm25[c["suite"]].scores(tokenize(c["q"][qname]))
        return sorted(range(len(s)), key=lambda i: (-s[i], i))
    repro = sum([ids[c["suite"]][i] for i in bm25_rank(c, "trusted")[:3]] == c["shown"][:3] for c in cases) / len(cases)
    print(f"BM25 reproduces the stored top-3 on {repro:.1%} of cases")

    runs: dict[str, dict] = {}       # method -> {case id: ranked clause ids}
    latency: dict[str, float] = {}

    def record(name, fn):
        t0 = time.perf_counter()
        runs[name] = {c["id"] + c["split"]: fn(c) for c in cases}
        latency[name] = (time.perf_counter() - t0) / len(cases) * 1000
        print(f"  {name:38s} {latency[name]:7.2f} ms/query")

    for qn in ("trusted", "evidence"):
        record(f"BM25 [{qn}]", lambda c, qn=qn: [ids[c["suite"]][i] for i in bm25_rank(c, qn)])

    dense_rank = {}
    for name, (hf, pool, qp, pp) in DENSE.items():
        try:
            enc = Dense(hf, pool, qp, pp)
        except Exception as e:                       # model not available offline
            print(f"  skip {name}: {type(e).__name__}")
            continue
        dvec = {s: enc.encode(doc_text[s], enc.pp) for s in handbooks}
        for qn in ("trusted", "evidence"):
            t0 = time.perf_counter()
            qv = enc.encode([c["q"][qn] for c in cases], enc.qp)
            ranks = {}
            for c, v in zip(cases, qv):
                s = dvec[c["suite"]] @ v
                ranks[c["id"] + c["split"]] = list(np.argsort(-s))
            key = f"{name} [{qn}]"
            dense_rank[key] = ranks
            runs[key] = {cid: [ids[c["suite"]][i] for i in ranks[cid]] for c in cases for cid in [c["id"] + c["split"]]}
            latency[key] = (time.perf_counter() - t0) / len(cases) * 1000
            print(f"  {key:38s} {latency[key]:7.2f} ms/query")
        del enc
        torch.cuda.empty_cache()

    def dev_r3(name):
        rows = [{"ranked": runs[name][c["id"] + c["split"]], "gold": c["gold"]} for c in cases if c["split"] == "dev"]
        return metrics(rows)["R@3"]

    # hybrid: BM25 + each dense model (same query type), reciprocal rank fusion
    for key in list(dense_rank):
        qn = key.split("[")[1].rstrip("]")
        name = f"Hybrid BM25+{key.split(' [')[0]} [{qn}]"
        record(name, lambda c, key=key, qn=qn: [ids[c["suite"]][i] for i in
                                                 rrf([bm25_rank(c, qn), dense_rank[key][c["id"] + c["split"]]])])
        latency[name] += latency[f"BM25 [{qn}]"] + latency[key]          # fusion needs both rankings

    # re-rank the top 10 of the best hybrid (chosen on dev) with each cross-encoder
    hybrids = [m for m in runs if m.startswith("Hybrid")]
    best_hybrid = max(hybrids, key=dev_r3) if hybrids else "BM25 [evidence]"
    for rname, hf in RERANKERS.items():
        try:
            rr = Reranker(hf)
        except Exception as e:
            print(f"  skip {rname}: {type(e).__name__}")
            continue
        qn = best_hybrid.split("[")[1].rstrip("]")
        text_of = {s: dict(zip(ids[s], doc_text[s])) for s in handbooks}

        def rerank(c, rr=rr, qn=qn):
            top = runs[best_hybrid][c["id"] + c["split"]][:K_MAX]
            sc = rr.scores(c["q"][qn], [text_of[c["suite"]][x] for x in top])
            return [top[i] for i in np.argsort(-sc)] + runs[best_hybrid][c["id"] + c["split"]][K_MAX:]
        record(f"{best_hybrid} + rerank {rname}", rerank)
        latency[f"{best_hybrid} + rerank {rname}"] += latency[best_hybrid]
        del rr
        torch.cuda.empty_cache()

    # rule precision on dev (how often the forced clause is a gold clause)
    rule_stats = defaultdict(lambda: [0, 0])
    for c in cases:
        if c["split"] != "dev":
            continue
        for r in rule_clauses(c):
            tag = r.split("-", 1)[1]
            rule_stats[tag][0] += 1
            rule_stats[tag][1] += r in c["gold"]

    global ACTIVE_RULES
    ACTIVE_RULES = {k for k, (f, g) in rule_stats.items() if f and g / f >= RULE_MIN_PRECISION}
    print(f"rules kept (dev precision >= {RULE_MIN_PRECISION}): {sorted(ACTIVE_RULES)}")

    # evidence rules on top of the BM25 baseline and of the best non-rule method (chosen on dev)
    base_best = max(runs, key=dev_r3)
    for base in dict.fromkeys(["BM25 [trusted]", "BM25 [evidence]", base_best]):
        record(f"Rules + {base}", lambda c, base=base: force_first(rule_clauses(c), runs[base][c["id"] + c["split"]]))
        latency[f"Rules + {base}"] += latency[base]

    # ------------------------------------------------------------------ results
    results = {}
    for name, ranks in runs.items():
        results[name] = {"latency_ms": latency[name]}
        for split in ("dev", "test"):
            rows = [{"ranked": ranks[c["id"] + c["split"]], "gold": c["gold"], "category": c["category"]}
                    for c in cases if c["split"] == split]
            m = metrics(rows)
            if split == "test":
                m["R@3_ci95"] = bootstrap_ci(rows)
            m["by_category_R@3"] = {}
            for cat in sorted({r["category"] for r in rows}):
                sub = [r for r in rows if r["category"] == cat]
                m["by_category_R@3"][cat] = {"n": len(sub), "R@3": metrics(sub)["R@3"]}
            results[name][split] = m
    best = max(results, key=lambda n: (results[n]["dev"]["R@3"], -results[n]["latency_ms"]))
    payload = {"best_on_dev": best, "bm25_reproduces_stored_top3": repro,
               "rule_precision_dev": {k: {"fired": f, "gold": g, "precision": g / f, "kept": k in ACTIVE_RULES}
                                   for k, (f, g) in rule_stats.items()},
               "results": results}
    (OUT / "results.json").write_text(json.dumps(payload, indent=1, default=float), encoding="utf-8")
    print(f"best on dev: {best}  R@3 dev={results[best]['dev']['R@3']:.3f} test={results[best]['test']['R@3']:.3f}")


if __name__ == "__main__":
    main()
