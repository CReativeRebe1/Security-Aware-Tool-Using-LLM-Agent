"""Where a gate decision comes from. The pages never read prediction files or call the gate code themselves;
they ask a *source* for a `GateRun`.

- RecordedSource: the real Run 1 predictions committed under results/data/run1 (all gates).
- LiveRulesSource: the B1 rules gate, run now on CPU with the project's own code.

Phase 2 adds a RemoteSource here (HTTP to the GPU server: GET /health, POST /gate, POST /resolve) that returns the
same GateRun, so no page has to change. If the server is down, the pages keep using RecordedSource.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import streamlit as st

from . import data as D
from sagate.config import load_condition, load_config
from sagate.evidence.mask import EvidenceMask
from sagate.gate.guards import GuardedGate
from sagate.gate.rules import RulesGate
from sagate.resolution.loop import resolve
from sagate.resolution.responders import FixedUserResponder, MockApprover, ScenarioResponder


@dataclass(frozen=True)
class GateInfo:
    key: str           # condition name = prediction file stem
    code: str          # B1 ... B5
    name: str          # plain-language name
    family: str        # rules | prompted | trained
    blurb: str


GATES: dict[str, GateInfo] = {g.key: g for g in [
    GateInfo("b1_rules", "B1", "Rules", "rules", "Hand-written if/then rules over the same evidence. No AI."),
    GateInfo("b2_prompt_binary", "B2", "Prompted AI · yes/no", "prompted",
             "Qwen3-8B with instructions only, no training. Can only say ALLOW or BLOCK."),
    GateInfo("b3_prompt_4way", "B3", "Prompted AI · 4 choices", "prompted",
             "Qwen3-8B with instructions only, no training. All four decisions."),
    GateInfo("b4_qlora_binary", "B4", "Trained AI · yes/no", "trained",
             "Qwen3-8B trained on our labels, but only ALLOW or BLOCK. Not trained yet."),
    GateInfo("b5_qlora_4way", "B5", "Trained AI · 4 choices", "trained",
             "Our gate: Qwen3-8B fine-tuned (QLoRA) on our labels, all evidence, all four decisions."),
    GateInfo("b5_guarded", "B5+G", "B5 + safety guards", "trained",
             "B5, then hard rules that can only make an ALLOW stricter, never looser."),
    GateInfo("b5_inferred_prov", "B5-R", "B5 · realistic provenance", "trained",
             "B5 when 'where did this come from' is guessed by string matching, as a real system must."),
]}
OURS = "b5_qlora_4way"
FAMILY_COLOR = {"trained": "#2a78d6", "prompted": "#eb6834", "rules": "#1baf7a"}   # validated palette


@dataclass
class GateRun:
    gate: GateInfo
    trace: dict | None          # ResolutionTrace.to_dict(), or None when there is no result
    source: str                 # recorded | live
    note: str | None = None     # why there is no result, or a caveat about the one shown


class RecordedSource:
    """Real predictions from Run 1."""

    def available(self, split: str) -> list[str]:
        return [k for k in GATES if D.predictions(split, k) is not None]

    def run(self, split: str, key: str, case_id: str, noisy: bool = False) -> GateRun:
        g = GATES[key]
        preds = D.predictions(split, key, noisy) if noisy else None
        note = None
        if preds is None:
            if noisy and D.predictions(split, key) is not None:
                note = "No confusing-reply run for this gate; showing the normal reply."
            preds = D.predictions(split, key)
        if preds is None:
            return GateRun(g, None, "recorded", "Not trained yet in Run 1.")
        if case_id not in preds:
            return GateRun(g, None, "recorded", "Not scored here: the case starts after an answered question, and a "
                                               "yes/no gate has no question rounds.")
        return GateRun(g, preds[case_id], "recorded", note)

    def all(self, split: str, case_id: str, noisy: bool = False) -> list[GateRun]:
        return [self.run(split, k, case_id, noisy) for k in GATES]


@dataclass(frozen=True)
class LiveSettings:
    provenance: str = "oracle"     # oracle | inferred | none
    authority: bool = True
    sensitivity: bool = True
    rag: bool = True
    guards: bool = False
    noisy: bool = False

    @property
    def is_default(self) -> bool:
        return self == LiveSettings()


@st.cache_resource(show_spinner=False)
def _live_env():
    cfg = load_config()
    return cfg, MockApprover(cfg.resources_dir), load_condition("b1_rules")


class LiveRulesSource:
    """B1 through the same path as `python -m sagate.eval.run_gate --condition b1_rules`: EvidenceMask -> RulesGate
    (optionally GuardedGate) -> resolution loop with the fixed user reply and the MockApprover. With default settings
    it reproduces the recorded NB02 predictions exactly (checked on all 448 test and dev cases)."""

    def run(self, split: str, case_id: str, s: LiveSettings = LiveSettings()) -> GateRun:
        cfg, approver, base = _live_env()
        cond = replace(base, provenance=s.provenance, authority=s.authority, sensitivity=s.sensitivity, rag=s.rag,
                       guards=s.guards)
        case = D.cases(split)[case_id]
        rules = RulesGate(cond.decision_space)
        gate = GuardedGate(rules, cond.decision_space) if s.guards else rules
        gi = EvidenceMask.from_condition(cond).apply(case.input, case.alt_provenance)
        # Annotated cases: the fallback responder answers from the gold final action and never reads AgentDojo data.
        user = FixedUserResponder(noisy=s.noisy, fallback=ScenarioResponder(None, cfg["resolution"]["user_noise"],
                                                                         s.noisy, cfg["seed"]))
        tr = resolve(case, gi, gate, user, approver, cond.name, cfg["resolution"]["max_rounds"], cond.resolution)
        return GateRun(GATES["b1_rules"], tr.to_dict(), "live")

    def matches_recorded(self, split: str, case_id: str) -> bool | None:
        rec = (D.predictions(split, "b1_rules") or {}).get(case_id)
        if rec is None:
            return None
        live = self.run(split, case_id).trace
        return all(live[k] == rec[k] for k in ("first_decision", "final_decision", "interactions"))


recorded = RecordedSource()
live = LiveRulesSource()
