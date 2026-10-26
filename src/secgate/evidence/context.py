"""Security context builder: (request, proposed call, conversation so far) -> GateInput.

The one place GateInputs are made — for test cases from logged traces, for training variants, inside the
resolution loop and in the live agent — so every gate sees the same format everywhere.
"""

from __future__ import annotations

import copy
from typing import Iterable, Sequence

from ..config import Config
from ..data.loaders import AgentDojoData, message_text
from ..gate.schema import GateInput
from .authority import AuthorityRegistry
from .policy_rag import PolicyRetriever, build_query
from .provenance import ContentBlock, build_provenance
from .sensitivity import SensitivityLabeler
from .tools import spec


class SuiteResources:
    def __init__(self, cfg: Config, data: AgentDojoData, suite: str):
        env = data.environment(suite, "default")
        self.authority = AuthorityRegistry(cfg.resources_dir, suite, env)
        self.sensitivity = SensitivityLabeler(cfg.resources_dir, suite, env)
        self.retriever = PolicyRetriever(cfg.resources_dir / "handbooks" / f"{suite}.md")


def content_blocks(messages: Sequence[dict], upto: int | None = None) -> list[ContentBlock]:
    """Tool outputs in messages[:upto], in order, as T1..Tn."""
    out = []
    for m in list(messages)[:upto]:
        if m.get("role") != "tool":
            continue
        tc = m.get("tool_call") or {}
        fn = tc.get("function", "unknown") if isinstance(tc, dict) else getattr(tc, "function", "unknown")
        text = message_text(m)
        if m.get("error"):
            text = f"{text}\n[error] {m['error']}".strip()
        out.append(ContentBlock(id=f"T{len(out) + 1}", function=fn, call_index=len(out), text=text,
                                third_party=spec(fn).third_party_output))
    return out


def _clip(text: str, n: int) -> tuple[str, bool]:
    if len(text) <= n:
        return text, False
    return text[: n - 16] + " …[truncated]", True


class ContextBuilder:
    def __init__(self, cfg: Config, data: AgentDojoData):
        self.cfg, self.data = cfg, data
        self.opts = cfg["context"]
        self._suites: dict[str, SuiteResources] = {}
        self.truncated = 0

    def suite(self, name: str) -> SuiteResources:
        if name not in self._suites:
            self._suites[name] = SuiteResources(self.cfg, self.data, name)
        return self._suites[name]

    def build(
        self,
        case_id: str,
        suite: str,
        user_prompt: str,
        proposed_call: dict,
        prior_calls: Iterable[dict],
        messages: Sequence[dict],
        upto: int | None = None,
        injections: Iterable[str] = (),
        goal_match: bool = False,
        modes: Sequence[str] = ("oracle", "inferred"),
    ) -> tuple[GateInput, dict]:
        """GateInput with the first provenance mode, plus extras:
        {"provenance": {other modes: records}, "retrieved_ids": top-k_eval clause ids}."""
        res = self.suite(suite)
        sp = spec(proposed_call["function"])
        action = {"function": proposed_call["function"], "args": copy.deepcopy(proposed_call.get("args") or {}),
                  "action_class": sp.action_class, "state_changing": sp.state_changing}

        blocks = content_blocks(messages, upto)
        prov = {m: build_provenance(action["args"], user_prompt, [copy.copy(b) for b in blocks], sp.action_class,
                                    mode=m, injections=injections, goal_match=goal_match) for m in modes}

        relations = [r["relation"] for r in res.authority.recipients(action, sp)]
        sens = res.sensitivity.assess(action, sp, relations)
        auth = res.authority.assess(action, sp, sens)
        k, k_eval = self.opts.get("rag_k", 3), self.opts.get("rag_k_eval", 5)
        ranked = res.retriever.retrieve(build_query(user_prompt, action["function"], sp.action_class, auth, sens),
                                        k=max(k, k_eval))

        shown = blocks[-self.opts.get("max_tool_outputs", 3):]
        content = []
        for b in shown:
            text, cut = _clip(b.text, self.opts.get("tool_output_chars", 1500))
            self.truncated += cut
            content.append({"id": b.id, "source": b.source, "text": text})

        gi = GateInput(
            case_id=case_id,
            suite=suite,
            request={"principal": res.authority.current_user, "prompt": user_prompt},
            action=action,
            prior_calls=[{"function": c["function"], "args": c.get("args") or {}} for c in prior_calls],
            provenance=prov[modes[0]],
            authority=auth,
            sensitivity=sens,
            policy=[c.to_dict() for c in ranked[:k]],
            content=content,
            resolution=[],
        )
        return gi, {"provenance": {m: prov[m] for m in modes[1:]}, "retrieved_ids": [c.id for c in ranked]}

    def from_proposal(self, row: dict, trace: dict, case_id: str,
                      goal_match: bool | None = None) -> tuple[GateInput, dict]:
        """From a tool_call_proposals row and its trace (oracle provenance first, inferred in extras).
        `goal_match` (does the call match the attacker's goal?) defaults to the row's heuristic flag."""
        return self.build(
            case_id=case_id,
            suite=row["suite"],
            user_prompt=row["user_prompt"],
            proposed_call=row["proposed_call"],
            prior_calls=row.get("prior_calls") or [],
            messages=trace["messages"],
            upto=row["message_index"],
            injections=(trace.get("injections") or {}).values(),
            goal_match=bool(row.get("matches_injection_task_ground_truth") if goal_match is None else goal_match),
        )


def with_round(gi: GateInput, round_no: int, decision: str, asked: dict, response: dict) -> GateInput:
    """Append one answered ASK_USER / ESCALATE round. A user's answer never changes authority facts; an approver's
    grant is recorded as an approval on the authority evidence (when that evidence is present)."""
    out = gi.copy()
    entry = {"round": round_no, "kind": decision,
             "asked": {k: v for k, v in asked.items() if v not in (None, "none")},
             "responder": response.get("responder"), "text": response.get("text", "")}
    if decision == "ESCALATE":
        entry["approved"] = response.get("approved")
        if response.get("approved") and out.authority is not None:
            out.authority.setdefault("approvals", []).append(
                {"by": response.get("responder"), "role": response.get("role"), "round": round_no})
    else:
        entry["confirmed"] = response.get("confirmed")
        entry["provides"] = response.get("provides")
    out.resolution.append(entry)
    return out
