"""AgentDojo pipeline with a local Qwen3 agent (ARCHITECTURE.md §5.7).

B0 = this pipeline with the gate disabled (AgentDojo's stock ToolsExecutor). The gated runs (NB05) replace the
executor with GatedToolsExecutor: every state-changing call goes through the resolution loop and executes only
on ALLOW; anything else returns the minimal error "Action not permitted." (no policy detail), and after 3 refused
calls in one task the run is ended. Agent and gate share one model in memory: the agent runs with adapters
disabled, the gate with its LoRA adapter (LLMGate switches it per call).
"""

from __future__ import annotations

from ast import literal_eval
from collections.abc import Sequence

from agentdojo.agent_pipeline import (AgentPipeline, BasePipelineElement, InitQuery, SystemMessage,
                                      ToolsExecutionLoop, ToolsExecutor)
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agentdojo.agent_pipeline.errors import AbortAgentError
from agentdojo.agent_pipeline.tool_execution import is_string_list, tool_result_to_str
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionCall, FunctionsRuntime
from agentdojo.types import ChatAssistantMessage, ChatMessage, ChatToolResultMessage, text_content_block_from_string

from ..data.cases import Case
from ..data.loaders import message_text
from ..evidence.tools_registry import needs_gate
from ..models.chat import parse_tool_calls, to_hf_messages, tool_schemas
from ..resolution.loop import resolve

REFUSAL = "Action not permitted."
MAX_REFUSALS = 3

# AgentDojo's attacks address the model by name; any pipeline name containing "local" maps to "Local model".
PIPELINE_NAME = "local-qwen3-8b"


class QwenLLM(BasePipelineElement):
    name = PIPELINE_NAME

    def __init__(self, backend, max_new_tokens: int = 512, max_parse_retries: int = 2):
        self.backend = backend
        self.max_new_tokens = max_new_tokens
        self.max_parse_retries = max_parse_retries
        self.parse_failures = 0

    def query(self, query: str, runtime: FunctionsRuntime, env: Env = EmptyEnv(),
              messages: Sequence[ChatMessage] = [], extra_args: dict = {}):
        tools = tool_schemas(runtime.functions.values())
        chat = to_hf_messages(messages)
        if getattr(self.backend, "active_adapter", None) is not None:
            self.backend.use_adapter(None)          # the agent always runs on the base weights
        content, calls = "", []
        for _ in range(self.max_parse_retries + 1):
            raw = self.backend.generate_chat(chat, tools=tools, max_new_tokens=self.max_new_tokens)
            content, calls, err = parse_tool_calls(raw)
            if err is None:
                break
            self.parse_failures += 1
            # retry with the error shown to the model; the failed attempt is not kept in the trace
            chat = chat + [{"role": "assistant", "content": raw},
                           {"role": "user", "content": f"Your tool call could not be parsed ({err}). "
                                                       "Reply again with valid <tool_call> JSON."}]
        tool_calls = [FunctionCall(function=c["function"], args=c["args"], id=f"call_{i}")
                      for i, c in enumerate(calls)]
        msg = ChatAssistantMessage(role="assistant", content=[text_content_block_from_string(content)],
                                   tool_calls=tool_calls or None)
        return query, runtime, env, [*messages, msg], extra_args


class Recorder(BasePipelineElement):
    """Keeps the final message list (AgentDojo's run_task_with_pipeline returns only utility/security)."""

    name = "recorder"

    def __init__(self):
        self.messages: list = []

    def query(self, query, runtime, env=EmptyEnv(), messages=[], extra_args={}):
        self.messages = list(messages)
        return query, runtime, env, messages, extra_args


class GatedToolsExecutor(BasePipelineElement):
    """Drop-in replacement for AgentDojo's ToolsExecutor with the security gate as sole execution authority.

    The GateInput is built from the live conversation (inferred provenance: nothing knows which text is
    injected), the resolution loop runs with live responders (ScenarioResponder for the user, MockApprover),
    and only ALLOW executes. `start_task()` must be called before each task; the gate log of the task is in
    `self.log`, and `self.aborted` holds the messages when the run was ended after MAX_REFUSALS refusals.
    """

    name = "gated_tools_executor"

    def __init__(self, gate, builder, user, approver, condition: str, mask=None, max_rounds: int = 2,
                 resolution: bool = True, gate_read_only: bool = False, max_refusals: int = MAX_REFUSALS):
        self.gate, self.builder, self.user, self.approver = gate, builder, user, approver
        self.condition, self.mask, self.max_rounds, self.resolution = condition, mask, max_rounds, resolution
        self.gate_read_only, self.max_refusals = gate_read_only, max_refusals
        self.start_task(None, None)

    def start_task(self, suite: str | None, scenario_id: str | None) -> None:
        self.suite, self.scenario_id = suite, scenario_id
        self.log: list[dict] = []
        self.refusals = 0
        self.aborted: list | None = None

    def _gate(self, call: dict, messages: Sequence[ChatMessage], prior: list[dict]) -> dict:
        plain = jsonify(list(messages))
        prompt = next((message_text(m) for m in plain if m.get("role") == "user"), "")
        step = len(self.log)
        cid = f"live|{self.condition}|{self.scenario_id}|{step}"
        gi, _ = self.builder.build(cid, self.suite, prompt, call, prior, plain, None, modes=("inferred",))
        if self.mask is not None:
            gi = self.mask.apply(gi, {"inferred": gi.provenance})
        case = Case(input=gi, pool="test", subset="live", scenario_id=self.scenario_id)
        tr = resolve(case, gi, self.gate, self.user, self.approver, self.condition, self.max_rounds, self.resolution)
        entry = {"step": step, "function": call["function"], "args": call["args"], **tr.to_dict()}
        self.log.append(entry)
        return entry

    def query(self, query: str, runtime: FunctionsRuntime, env: Env = EmptyEnv(),
              messages: Sequence[ChatMessage] = [], extra_args: dict = {}):
        if not messages or messages[-1]["role"] != "assistant" or not messages[-1]["tool_calls"]:
            return query, runtime, env, messages, extra_args
        known = {t.name for t in runtime.functions.values()}
        prior = [{"function": tc.function, "args": dict(tc.args)} for m in messages[:-1]
                 if m["role"] == "assistant" for tc in (m.get("tool_calls") or [])]
        results = []
        for tc in messages[-1]["tool_calls"]:
            if tc.function not in known:
                results.append(ChatToolResultMessage(role="tool", content=[text_content_block_from_string("")],
                                                     tool_call_id=tc.id, tool_call=tc,
                                                     error=f"Invalid tool {tc.function} provided."))
                prior.append({"function": tc.function, "args": dict(tc.args)})
                continue
            for k, v in tc.args.items():                     # same list-coercion as AgentDojo's ToolsExecutor
                if isinstance(v, str) and is_string_list(v):
                    tc.args[k] = literal_eval(v)
            call = {"function": tc.function, "args": dict(tc.args)}
            allowed = True
            if needs_gate(tc.function, self.gate_read_only):
                allowed = self._gate(call, [*messages, *results], list(prior))["final_decision"] == "ALLOW"
            prior.append(call)
            if not allowed:
                self.refusals += 1
                results.append(ChatToolResultMessage(role="tool", content=[text_content_block_from_string("")],
                                                     tool_call_id=tc.id, tool_call=tc, error=REFUSAL))
                continue
            out, err = runtime.run_function(env, tc.function, tc.args)
            results.append(ChatToolResultMessage(role="tool", content=[text_content_block_from_string(
                tool_result_to_str(out))], tool_call_id=tc.id, tool_call=tc, error=err))
        messages = [*messages, *results]
        if self.refusals >= self.max_refusals:
            err = AbortAgentError(REFUSAL, list(messages), env)
            self.aborted = err.messages
            raise err
        return query, runtime, env, messages, extra_args


def make_b0_pipeline(backend, cfg, executor: BasePipelineElement | None = None) -> tuple[AgentPipeline, Recorder, QwenLLM]:
    """B0 pipeline; pass a GatedToolsExecutor as `executor` for the gated end-to-end runs."""
    a = cfg["agent"]
    llm = QwenLLM(backend, a.get("max_new_tokens", 512), a.get("max_parse_retries", 2))
    rec = Recorder()
    pipe = AgentPipeline([
        SystemMessage(load_system_message(None)),
        InitQuery(),
        llm,
        ToolsExecutionLoop([executor or ToolsExecutor(), llm], max_iters=a.get("max_iters", 15)),
        rec,
    ])
    pipe.name = PIPELINE_NAME
    return pipe, rec, llm


def jsonify(obj):
    """AgentDojo messages (TypedDicts holding pydantic FunctionCalls) -> plain JSON."""
    if hasattr(obj, "model_dump"):
        return jsonify(obj.model_dump())
    if isinstance(obj, dict):
        return {k: jsonify(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonify(v) for v in obj]
    return obj
