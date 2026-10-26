"""Security context builder: assembles a GateInput from (prompt, proposed call, conversation, environment).

Used by the case builder (offline, from logged traces), the resolution loop (adds answers from earlier rounds)
and the live agent pipeline. The SFT builder and evaluator then apply the same EvidenceMask (P3).
"""

from __future__ import annotations

import copy
from typing import Iterable, Sequence

from ..config import Config
from ..data.loaders import AgentDojoData, message_text
from ..gate.schema import GateInput
from .authority import AuthorityRegistry
from .policy_rag import PolicyRetriever, build_query
from .provenance import ToolBlock, build_records
from .sensitivity import SensitivityLabeler
from .tools_registry import THIRD_PARTY_OUTPUT, spec


class SuiteResources:
    def __init__(self, cfg: Config, data: AgentDojoData, suite: str):
        env = data.environment(suite, "default")
        self.authority = AuthorityRegistry(cfg.resources_dir, suite, env)
        self.sensitivity = SensitivityLabeler(cfg.resources_dir, suite, env)
        self.retriever = PolicyRetriever(cfg.resources_dir / "handbooks" / f"{suite}.md")


def tool_blocks(messages: Sequence[dict], upto: int | None = None) -> list[ToolBlock]:
    """Tool outputs in messages[:upto], in order, as T1..Tn."""
    blocks, call_idx = [], 0
    for m in list(messages)[:upto]:
        if m.get("role") != "tool":
            continue
        tc = m.get("tool_call") or {}
        fn = tc.get("function", "unknown") if isinstance(tc, dict) else getattr(tc, "function", "unknown")
        text = message_text(m)
        if m.get("error"):
            text = (text + "\n" if text else "") + f"[error] {m['error']}"
        blocks.append(ToolBlock(id=f"T{len(blocks) + 1}", function=fn, call_index=call_idx, text=text,
                                third_party=fn in THIRD_PARTY_OUTPUT))
        call_idx += 1
    return blocks


def _truncate(text: str, n: int) -> tuple[str, bool]:
    if len(text) <= n:
        return text, False
    return text[: n - 20] + " …[truncated]", True


class ContextBuilder:
    def __init__(self, cfg: Config, data: AgentDojoData):
        self.cfg, self.data = cfg, data
        self.ctx = cfg["context"]
        self._suites: dict[str, SuiteResources] = {}
        self.truncations = 0

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
        injection_goal_match: bool = False,
        modes: Sequence[str] = ("oracle", "inferred"),
    ) -> tuple[GateInput, dict]:
        """Return (GateInput with the first provenance mode, extras).

        extras = {"provenance": {other_mode: records}, "retrieved_ids": top-5 clause ids (for Recall@5)}."""
        res = self.suite(suite)
        sp = spec(proposed_call["function"])
        call = {"function": proposed_call["function"], "args": dict(proposed_call.get("args") or {}),
                "state_changing": sp.state_changing, "action": sp.action}

        blocks = tool_blocks(messages, upto)
        prov = {}
        for mode in modes:
            prov[mode] = build_records(call["args"], user_prompt, [copy.copy(b) for b in blocks], mode=mode,
                                       injections=injections if mode == "oracle" else (),
                                       injection_goal_match=injection_goal_match if mode == "oracle" else False)

        dests = res.authority.destinations(call, sp)
        prior_calls = [{"function": c["function"], "args": c.get("args", {})} for c in prior_calls]
        sens = res.sensitivity.assess(call, sp, [c for c, _ in dests], prior_calls)
        auth = res.authority.assess(call, sp, sens)
        query = build_query(user_prompt, call["function"], sp.action, auth, sens)
        k = self.ctx.get("rag_k", 3)
        ranked = res.retriever.retrieve(query, k=max(k, 5))
        clauses = [c.as_dict() for c in ranked[:k]]

        shown = blocks[-self.ctx.get("max_untrusted_blocks", 3):] if blocks else []
        untrusted = []
        for b in shown:
            text, cut = _truncate(b.text, self.ctx.get("untrusted_max_chars", 1500))
            self.truncations += cut
            untrusted.append({"id": b.id, "source": b.source, "text": text})

        gi = GateInput(
            case_id=case_id,
            suite=suite,
            user={"principal_id": res.authority.current_user, "prompt": user_prompt},
            proposed_call=call,
            prior_calls=prior_calls,
            provenance=prov[modes[0]],
            authority=auth,
            sensitivity=sens,
            policy_clauses=clauses,
            untrusted_content=untrusted,
            resolution_history=[],
        )
        return gi, {"provenance": {m: prov[m] for m in modes[1:]}, "retrieved_ids": [c.id for c in ranked]}

    def from_proposal(self, row: dict, trace: dict, case_id: str | None = None) -> tuple[GateInput, dict]:
        """Build from a tool_call_proposals row and its trace (oracle first, inferred in extras)."""
        return self.build(
            case_id=case_id or row["proposal_id"],
            suite=row["suite"],
            user_prompt=row["user_prompt"],
            proposed_call=row["proposed_call"],
            prior_calls=row.get("prior_calls", []),
            messages=trace["messages"],
            upto=row["message_index"],
            injections=(trace.get("injections") or {}).values(),
            # "seen before the call" is implied: the origin must be an injected block shown before the call
            injection_goal_match=bool(row.get("matches_injection_task_ground_truth")),
        )


def with_resolution(gi: GateInput, round_no: int, kind: str, gate_output: dict, response: dict) -> GateInput:
    """Append one answered ASK_USER/ESCALATE round. Responses never change authority facts
    (`user_may_authorize`, `required_role`); an approver's grant is recorded as a prior approval."""
    out = gi.copy()
    entry = {
        "round": round_no,
        "kind": kind,
        "asked": {k: gate_output.get(k) for k in ("missing_evidence", "required_authority") if gate_output.get(k)},
        "responder": response.get("responder"),
        "response": response.get("text", ""),
    }
    if kind == "ESCALATE":
        entry["approved"] = bool(response.get("approved"))
        if response.get("approved") and out.authority is not None:
            out.authority.setdefault("prior_approvals", []).append(
                {"by": response.get("responder"), "role": response.get("role"), "round": round_no})
    else:
        entry["provides"] = response.get("provides")
        entry["confirmed"] = response.get("confirmed")
    out.resolution_history.append(entry)
    return out
