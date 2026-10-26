"""AgentDojo pipeline with a local Qwen3 agent (ARCHITECTURE.md §5.7).

B0 = this pipeline with the gate disabled. The gated executor (GatedToolsExecutor) is added for the end-to-end
B5 runs (NB05); B0 uses AgentDojo's stock ToolsExecutor.
"""

from __future__ import annotations

from collections.abc import Sequence

from agentdojo.agent_pipeline import (AgentPipeline, BasePipelineElement, InitQuery, SystemMessage,
                                      ToolsExecutionLoop, ToolsExecutor)
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionCall, FunctionsRuntime
from agentdojo.types import ChatAssistantMessage, ChatMessage, text_content_block_from_string

from ..models.chat import parse_tool_calls, to_hf_messages, tool_schemas

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


def make_b0_pipeline(backend, cfg) -> tuple[AgentPipeline, Recorder, QwenLLM]:
    a = cfg["agent"]
    llm = QwenLLM(backend, a.get("max_new_tokens", 512), a.get("max_parse_retries", 2))
    rec = Recorder()
    pipe = AgentPipeline([
        SystemMessage(load_system_message(None)),
        InitQuery(),
        llm,
        ToolsExecutionLoop([ToolsExecutor(), llm], max_iters=a.get("max_iters", 15)),
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
