# Stress-test set

90 gold-labelled gate cases (15 families, 33 variants) written to probe the weaknesses listed in
[`docs/CODE_REVIEW.md`](../../docs/CODE_REVIEW.md). The per-case failure report is
[`docs/STRESS_TEST_REPORT.md`](../../docs/STRESS_TEST_REPORT.md).

| File | What it is |
|---|---|
| `specs/*.yaml` | The hand-written source, in the same format as `data/synthetic_data/specs`. Edit these, not the JSONL. |
| `cases.jsonl` | 90 `Case` rows, `pool: test`, `subset: decision_only`, with gold labels and fixed user replies. |
| `baseline_rules.json` | B1 rules and B1 with guards on every case, with oracle and with inferred provenance. |
| `probes.yaml` | 4 inputs that cannot be cases because building the gate input raises, or the value is not valid JSON. |
| `build.py` | Rebuilds `cases.jsonl` and the baseline, and runs the probes. |

```bash
PYTHONPATH=src python data/stress_test/build.py            # rebuild and print the rules baseline
PYTHONPATH=src python data/stress_test/build.py --check    # print only, write nothing
# any gate, same command as the frozen test set:
PYTHONPATH=src python -m sagate.eval.run_gate --condition b5_qlora_4way --cases data/stress_test/cases.jsonl \
       --pool test --adapter-dir <adapters> --out outputs/predictions/stress
PYTHONPATH=src python -m sagate.eval.report --cases data/stress_test/cases.jsonl --pred outputs/predictions/stress/*.jsonl
```

## Read before using

- **Labels are the author's intended labels, not adjudicated.** They were written by Claude during the code review
  (`meta.author`), with `meta.reviewed_by` empty. A team member should review them before any number is reported.
- **Never train on these cases.** They are tagged `pool: test`, so `build_sft` refuses them.
- **It is a targeted set, not a sample.** Most families were chosen because the pipeline was expected to fail on them,
  so its rates say nothing about overall gate quality. Report it separately from the frozen test set.
- Every family has a control variant where the pipeline is expected to be right. A gate that fails a control has a
  different problem from the one the family targets.
- `meta.targets` holds the finding each case probes (`H1`, `H2`, `M3`, `M4`, `M9`, `L1`, `N1`–`N3`).
