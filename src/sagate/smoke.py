"""NB00 smoke test: load the model, measure prefill/decode throughput, run one gate call (B3 prompt) and one
AgentDojo task (B0). Writes throughput.json so the GPU-hour estimates in ARCHITECTURE.md §9.2 can be replaced
by measured numbers.

  python -m sagate.smoke --out outputs/nb00 [--model-id Qwen/Qwen3-0.6B] [--skip-agent]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .config import load_condition, load_config
from .data.build_cases import make_case_id
from .data.loaders import AgentDojoData
from .evidence.context_builder import ContextBuilder
from .evidence.tools_registry import is_state_changing
from .gate.prompts import chat_messages
from .manifest import write_manifest


def _sync(backend) -> None:
    if backend.torch.cuda.is_available():
        backend.torch.cuda.synchronize()


def throughput(backend, n_prefill: int = 1024, n_decode: int = 64) -> dict:
    torch = backend.torch
    ids = torch.randint(100, 20000, (1, n_prefill), device=backend.device)
    with torch.inference_mode():
        backend.model(input_ids=ids)                    # warm-up at the measured shape (kernel selection)
        _sync(backend)
        t0 = time.time()
        backend.model(input_ids=ids)
        _sync(backend)
        prefill = time.time() - t0
        t0 = time.time()
        out = backend.model.generate(input_ids=ids[:, :64], attention_mask=torch.ones_like(ids[:, :64]),
                                     max_new_tokens=n_decode, min_new_tokens=n_decode, do_sample=False,
                                     pad_token_id=backend.tokenizer.eos_token_id)
        _sync(backend)
        decode = time.time() - t0
    gen = out.shape[1] - 64
    res = {"prefill_tokens": n_prefill, "prefill_s": prefill, "prefill_tok_s": n_prefill / prefill,
           "decode_tokens": gen, "decode_s": decode, "decode_tok_s": gen / decode}
    if torch.cuda.is_available():
        res["gpu"] = torch.cuda.get_device_name(0)
        res["max_mem_gb"] = torch.cuda.max_memory_allocated() / 1e9
    return res


def gate_call(backend, cfg, data) -> dict:
    from .gate.llm_gate import LLMGate

    row = next(data.iter_proposals(lambda r: r["suite"] == "banking" and r["injection_task_id"]
                                   and is_state_changing(r["proposed_call"]["function"])))
    trace = data.traces_by_id([row["trace_id"]])[row["trace_id"]]
    gi, _ = ContextBuilder(cfg, data).from_proposal(row, trace, case_id=make_case_id(row))
    cond = load_condition("b3_prompt_4way")
    gate = LLMGate(backend, cond.decision_space, cond.intermediate)
    t0 = time.time()
    out = gate.decide(gi)
    t1 = time.time()
    gate.decide(gi.copy())                              # second call: prompt-prefix cache warm
    prompt_tokens = len(backend.encode(backend.chat_prefix(chat_messages(gi, cond.decision_space))))
    return {"case_id": gi.case_id, "output": out.to_dict(), "seconds": t1 - t0, "seconds_cached": time.time() - t1,
            "prompt_tokens": prompt_tokens}


def agent_task(backend, cfg) -> dict:
    from agentdojo.task_suite.load_suites import get_suite

    from .agent.pipeline import jsonify, make_b0_pipeline

    suite = get_suite(cfg["agent"]["benchmark_version"], "banking")
    pipeline, rec, llm = make_b0_pipeline(backend, cfg)
    t0 = time.time()
    utility, _ = suite.run_task_with_pipeline(pipeline, suite.get_user_task_by_id("user_task_3"), None, {})
    msgs = jsonify(rec.messages)
    return {"utility": bool(utility), "seconds": time.time() - t0, "parse_failures": llm.parse_failures,
            "tool_calls": [tc for m in msgs if m.get("role") == "assistant" for tc in (m.get("tool_calls") or [])],
            "final_answer": next((m["content"] for m in reversed(msgs) if m.get("role") == "assistant"), None)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--model-id", default=None)
    ap.add_argument("--skip-agent", action="store_true")
    a = ap.parse_args(argv)
    from .models.backend import backend_from_config

    cfg = load_config(a.config)
    data = AgentDojoData(cfg.data_dir)
    out = Path(a.out) if a.out else cfg.outputs_dir / "nb00"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    backend = backend_from_config(cfg, model_id=a.model_id)
    res = {"model_id": backend.model_id, "load_s": time.time() - t0}
    res["throughput"] = throughput(backend)
    print(json.dumps(res, indent=1), flush=True)
    res["gate_call"] = gate_call(backend, cfg, data)
    print(json.dumps(res["gate_call"], indent=1, default=str), flush=True)
    if not a.skip_agent:
        res["agent_task"] = agent_task(backend, cfg)
        print(json.dumps(res["agent_task"], indent=1, default=str), flush=True)
    (out / "throughput.json").write_text(json.dumps(res, indent=1, default=str))
    write_manifest(out / "manifest.json", cfg, extra={"stage": "nb00", "model_id": backend.model_id})
    print(f"wrote {out / 'throughput.json'}")


if __name__ == "__main__":
    main()
