import pytest

pytest.importorskip("agentdojo")

from agentdojo.agent_pipeline.errors import AbortAgentError  # noqa: E402
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402
from agentdojo.types import ChatAssistantMessage, ChatUserMessage, text_content_block_from_string  # noqa: E402

from sagate.agent.pipeline import REFUSAL, GatedToolsExecutor  # noqa: E402
from sagate.gate.schema import GateOutput  # noqa: E402
from sagate.resolution.responders import MockApprover, ScenarioResponder  # noqa: E402

PAYEE = "GB29NWBK60161331926819"


class FixedGate:
    def __init__(self, decision):
        self.decision, self.seen = decision, []

    def decide(self, gi):
        self.seen.append(gi)
        return GateOutput(decision=self.decision, missing_evidence="none", required_authority="current_user")


def _setup(cfg, data, builder, decision):
    suite = get_suite(cfg["agent"]["benchmark_version"], "banking")
    env = suite.load_and_inject_default_environment({})
    gate = FixedGate(decision)
    ex = GatedToolsExecutor(gate, builder, ScenarioResponder(data, noise=0.0), MockApprover(cfg.resources_dir), "t")
    ex.start_task("banking", "banking|user_task_1|benign")
    return FunctionsRuntime(suite.tools), env, gate, ex


def _msgs(*calls):
    tcs = [FunctionCall(function=f, args=a, id=f"c{i}") for i, (f, a) in enumerate(calls)]
    return [ChatUserMessage(role="user", content=[text_content_block_from_string(f"Send 10 to {PAYEE}.")]),
            ChatAssistantMessage(role="assistant", content=[text_content_block_from_string("")], tool_calls=tcs)]


def test_refused_call_does_not_execute(cfg, data, builder):
    runtime, env, gate, ex = _setup(cfg, data, builder, "BLOCK")
    n0 = len(env.bank_account.transactions)
    _, _, env, msgs, _ = ex.query("q", runtime, env, _msgs(("get_balance", {}),
                                                            ("send_money", {"recipient": PAYEE, "amount": 10,
                                                                            "subject": "x", "date": "2022-01-01"})))
    tool = [m for m in msgs if m["role"] == "tool"]
    assert tool[0]["error"] is None                           # read-only: bypasses the gate
    assert tool[1]["error"] == REFUSAL and len(env.bank_account.transactions) == n0
    assert len(gate.seen) == 1 and gate.seen[0].provenance[0]["trust"] == "trusted"      # live inferred provenance
    assert ex.log[0]["final_decision"] == "BLOCK" and ex.refusals == 1


def test_allowed_call_executes_and_refusals_abort(cfg, data, builder):
    runtime, env, _, ex = _setup(cfg, data, builder, "ALLOW")
    n0 = len(env.bank_account.transactions)
    send = ("send_money", {"recipient": PAYEE, "amount": 10, "subject": "x", "date": "2022-01-01"})
    _, _, env, msgs, _ = ex.query("q", runtime, env, _msgs(send))
    assert msgs[-1]["error"] is None and len(env.bank_account.transactions) == n0 + 1
    runtime, env, _, ex = _setup(cfg, data, builder, "BLOCK")
    with pytest.raises(AbortAgentError):
        ex.query("q", runtime, env, _msgs(send, send, send))
    assert ex.aborted is not None and ex.aborted[-1]["role"] == "assistant" and ex.refusals == 3
