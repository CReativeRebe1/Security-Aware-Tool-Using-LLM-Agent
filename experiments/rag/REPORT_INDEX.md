# Policy retrieval experiment 2: fact index

**Chosen: BM25 + evidence words + a fact-to-clause index, fused, 8 clauses.** Dev Recall@8 **0.946**, against
**0.378** (Recall@3) for the retriever used so far. It needs no models and no GPU. It is implemented in branch
`valhalla` (`sagate.evidence.policy_index`, `sagate.evidence.mask.retrieve_clauses`).

Data: the frozen human-labelled splits (`HumanLabelDataset`). The index is built from **train** (1,049 cases) and
scored on **dev** (236 cases, other scenario families). The test split was not used. Run:
`python experiments/rag/run_index_exp.py --train <train.jsonl> --dev <dev.jsonl>` (results in
`results/index_results.json`).

## How it works

1. **BM25 + evidence words** (from experiment 1): the query adds plain words for evidence the gate already has
   (instruction from content, arguments copied from content, earlier clarification rounds).
2. **Fact index**: from the training labels, which clauses go with which facts the gate sees (action, payee or
   recipient class, sensitivity, provenance trust, authority basis, earlier rounds). Facts seen in fewer than 5
   training cases are ignored.
3. **Fusion**: the two rankings are merged by reciprocal rank (1 / (10 + rank)); the top 8 clauses are shown.

Each condition retrieves from the evidence it may see, so ablations cannot get masked evidence back through the clauses.

## Results (dev)

| Retriever | Recall@3 | Recall@5 | Recall@8 |
|---|---|---|---|
| BM25, trusted query (used so far) | 0.378 | 0.531 | 0.640 |
| BM25 + evidence words (experiment 1) | 0.583 | 0.669 | 0.768 |
| Fact index alone | 0.507 | 0.686 | 0.784 |
| **BM25 + evidence + fact index (chosen)** | **0.640** | **0.764** | **0.946** |
| Same, index from generated cases only (no human labels) | 0.556 | 0.643 | 0.695 |
| Routing by handbook section (tried, not kept) | — | 0.661 | — |

All gold clauses in the top 8: 209 of 236 cases with the chosen method.

**An index from generated cases alone is not enough:** our generator covers only 20 of 48 clauses, so the index
from it is worse than BM25 + evidence alone. Planned: generate cases per clause and per clause combination, added
to the index at a lower weight, so rare combinations still get some coverage. They supplement the labelled cases;
they do not replace them.

## Cost (dev, measured with the Qwen3 tokenizer)

| | Previous (BM25, 3 clauses) | Chosen (8 clauses) |
|---|---|---|
| Correct clauses shown | 0.38 | 0.95 |
| Retrieval time | 0.32 ms per query | 0.39 ms per query |
| Clause tokens per prompt | ~150 | ~420 |
| Prompt tokens, median / max | 1,188 / 1,585 | 1,446 / 1,851 (+22%) |
| Gate call on a T4 | ~1.5 s | ~1.8 s (estimate) |
| Extra files | none | `resources/policy_index.json`, 22 KB |
| Needs labelled data | no | yes, or per-clause coverage cases |

Training max length was raised from 2,560 to 3,072 tokens so long generated examples are not dropped (121 of 1,000
would be at 2,560, 8 at 3,072).

## Edge cases and fallbacks

| Case | Behaviour |
|---|---|
| No index file (new deployment) | Plain BM25 + evidence words (dev Recall@8 0.768) |
| Handbook edited after the index was built | Index ignored with a warning, BM25 used; rebuild with `python -m sagate.evidence.policy_index` |
| Index names a clause the handbook no longer has | Clause skipped |
| A new kind of call (no known facts) | BM25 ranking only; still 8 clauses |
| Empty user prompt | Still 8 clauses (facts and evidence words) |
| Masked evidence (ablations) | Those facts and words are absent from retrieval |
| Index built from dev/test cases | Refused (`LeakageError`) |

## Caveats

- The index learns which clauses **our annotators cite**. Dev uses different scenario families, so it generalises
  across families, but live AgentDojo runs may differ.
- Experiment 1 chose its method on 2,000 synthetic cases and checked it on the old 160-case test set; this
  experiment uses only the frozen train and dev splits.
- For other organisations with their own rules: write the handbook, generate per-clause coverage cases (or label a
  set), rebuild the index; with neither, the system still works on BM25 + evidence words.
