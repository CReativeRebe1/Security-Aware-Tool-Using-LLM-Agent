"""Smoke test: load the model, measure prefill / decode / gate-call speed, decide one real case with the prompted
four-way gate, and (optionally) run one AgentDojo task end to end. Writes throughput.json so GPU-hour estimates
can be replaced by measured numbers.

  python -m secgate.smoke --out outputs/smoke [--model-id Qwen/Qwen3-0.6B] [--skip-agent]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .config import load_condition, load_config
from .data.build_cases import case_id_for
from .data.loaders import AgentDojoData, scenario_id
from .data.splits import Splits
from .evidence.context import ContextBuilder
from .evidence.tools import is_state_changing
from .manifest import write_manifest


def _sync(torch) -> None:
    if torch.cuda.is_available():
        torch.cuda.synchronize()


def throughput(backend, n_prefill: int = 1024, n_decode: int = 64) -> dict:
    torch = backend.torch
    ids = torch.randint(100, 20000, (1, n_prefill), device=backend.device)
    with torch.inference_mode():
        backend.model(input_ids=ids[:, :16])
        _sync(torch)
        t0 = time.time()
        backend.model(input_ids=ids)
        _sync(torch)
        prefill = time.time() - t0
        t0 = time.time()
        backend.model.generate(input_ids=ids[:, :32], attention_mask=torch.ones_like(ids[:, :32]),
                               max_new_tokens=n_decode, min_new_tokens=n_decode, do_sample=False,
                               pad_token_id=backend.tokenizer.eos_token_id)
        _sync(torch)
        decode = time.time() - t0
    return {"prefill_tok_per_s": round(n_prefill / prefill, 1), "decode_tok_per_s": round(n_decode / decode, 2)}


def one_case(cfg, data: AgentDojoData):
    """First state-changing test-pool proposal, built into a case."""
    from .data.cases import Case

    splits = Splits(data)
    for r in data.iter_proposals(lambda r: r.get("user_task_id") and is_state_changing(r["proposed_call"]["function"])):
        sid = scenario_id(r["suite"], r["user_task_id"], r["injection_task_id"])
        if sid in data.scenarios and splits.in_pool(sid, "test"):
            trace = data.traces_by_id([r["trace_id"]])[r["trace_id"]]
            gi, extras = ContextBuilder(cfg, data).from_proposal(r, trace, case_id_for(r))
            return Case(input=gi, pool="test", scenario_id=sid, alt_provenance=extras["provenance"])
    raise RuntimeError("no test proposal found")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--skip-agent", action="store_true")
    a = ap.parse_args(argv)

    from .gate.llm_gate import LLMGate
    from .gate.prompts import chat_messages
    from .models.backend import load_backend

    cfg = load_config(a.config)
    out_dir = Path(a.out) if a.out else cfg.outputs_dir / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    data = AgentDojoData(cfg.data_dir)
    report: dict = {}

    t0 = time.time()
    backend = load_backend(cfg, model_id=a.model_id)
    report["model_id"] = backend.model_id
    report["load_s"] = round(time.time() - t0, 1)
    torch = backend.torch
    report["device"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    report.update(throughput(backend))
    print("throughput:", report, flush=True)

    cond = load_condition("b3_prompt_4way")
    case = one_case(cfg, data)
    gate = LLMGate(backend, cond.decision_space, cond.intermediate, name=cond.name)
    prompt_tokens = len(backend.encode(backend.chat_prefix(chat_messages(case.input, cond.decision_space))))
    t0 = time.time()
    out = gate.decide(case.input)
    report["gate_call_s"] = round(time.time() - t0, 2)
    report["gate_prompt_tokens"] = prompt_tokens
    report["gate_case"] = case.case_id
    report["gate_output"] = out.answer()
    report["gate_p_allow"] = out.p_allow
    print("gate:", report["gate_output"], f"p_allow={out.p_allow:.3f}", f"{report['gate_call_s']}s", flush=True)

    if not a.skip_agent:
        from agentdojo.task_suite.load_suites import get_suite

        from .agent.pipeline import make_pipeline

        pipe, rec, agent = make_pipeline(backend, cfg)
        suite = get_suite(cfg["agent"]["benchmark_version"], "banking")
        t0 = time.time()
        utility, _ = suite.run_task_with_pipeline(pipe, suite.get_user_task_by_id("user_task_0"), None, {})
        report["agent_task_s"] = round(time.time() - t0, 1)
        report["agent_utility"] = bool(utility)
        report["agent_turns"] = sum(m["role"] == "assistant" for m in rec.messages)
        report["agent_parse_failures"] = agent.parse_failures
        print("agent:", {k: report[k] for k in report if k.startswith("agent")}, flush=True)

    (out_dir / "throughput.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    write_manifest(out_dir / "manifest.json", cfg, extra={"stage": "smoke", "model_id": backend.model_id})
    print(f"-> {out_dir / 'throughput.json'}")


if __name__ == "__main__":
    main()
