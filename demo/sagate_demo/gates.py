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
    code: str          # short label in tables and lanes
    name: str          # plain-language name
    family: str        # rules | prompted | trained | final
    blurb: str
    report: str = ""   # key in data/reported.json, when the team's final reports have this gate


# The names follow the team's final reports: "B5" is the final trained model, "Final" is B5 inside the GateExp rule
# layers. The earlier trained versions keep their place in the story as v1 (Run 1), v2 and v3.
GATES: dict[str, GateInfo] = {g.key: g for g in [
    GateInfo("b1_rules", "B1", "Rules only", "rules", "Hand-written if/then rules over the same evidence. No AI.", "b1"),
    GateInfo("b2_prompt_binary", "B2", "Prompted AI · yes/no", "prompted",
             "Qwen3-8B with instructions only, no training. Can only say ALLOW or BLOCK.", "b2"),
    GateInfo("b3_prompt_4way", "B3", "Prompted AI · 4 choices", "prompted",
             "Qwen3-8B with instructions only, no training. All four decisions.", "b3"),
    GateInfo("b5_qlora_4way", "v1", "First trained gate (Run 1)", "trained",
             "The first fine-tuned four-way gate (Run 1): Qwen3-8B with QLoRA on our labels, all evidence."),
    GateInfo("b5_guarded", "v1+G", "v1 + safety guards", "trained",
             "v1, then hard rules that can only make an ALLOW stricter, never looser (Run 1)."),
    GateInfo("b5_inferred_prov", "v1-R", "v1 · guessed provenance", "trained",
             "v1 when 'where did this come from' is guessed by string matching, as a real system must (Run 1)."),
    GateInfo("b5_v2_gateexp", "v2", "B5 v2 + GateExp layers", "trained",
             "Second version: a retrained model inside layers of facts, hard rules and after-checks (GateExp)."),
    GateInfo("b5_v3_combo_gateexp", "v3", "B5 v3 + GateExp layers", "trained",
             "Third version: retrained with factor-combination data, plus two rounds of review fixes. Replaced by the "
             "final design before the test run."),
    GateInfo("b5_v4_combo", "B5", "B5 alone (final model)", "trained",
             "The final trained model: Qwen3-8B with QLoRA, 2,698 examples, cost-matrix loss, four decisions.", "b5"),
    GateInfo("b5_v4_combo_gateexp", "Final", "Final system: B5 + GateExp", "final",
             "The final trained model inside the GateExp rule layers. Scored on test once, at the end.", "final"),
]}
FINAL = "b5_v4_combo_gateexp"        # the final system
B5_FINAL = "b5_v4_combo"             # the final model alone
V1 = "b5_qlora_4way"                 # Run 1's trained gate
HISTORY = ("b5_v3_combo_gateexp", "b5_v2_gateexp")    # earlier versions, newest first
OURS = V1                            # kept for older imports
FAMILY_COLOR = {"rules": "#199e70", "prompted": "#d95926", "trained": "#7b80f0", "ablation": "#c98500",
                "final": "#d55181"}   # validated in this order, light and dark
# Per-gate colours for grouped bars (order B1, B3, v1, v2, v3, Final validated for adjacent pairs, light and dark).
GATE_COLOR = {"b1_rules": "#199e70", "b3_prompt_4way": "#d95926", "b5_qlora_4way": "#3987e5",
              "b5_v2_gateexp": "#d55181", "b5_v3_combo_gateexp": "#c98500", FINAL: "#7b80f0"}


@dataclass
class GateRun:
    gate: GateInfo
    trace: dict | None          # ResolutionTrace.to_dict(), or None when there is no result
    source: str                 # recorded | live
    note: str | None = None     # why there is no result, or a caveat about the one shown


def _pending_note(key: str, split: str) -> str:
    """For the final model / system before their case files are committed: say so, with the reported number."""
    g = GATES[key]
    off = D.official(g.report, split) if g.report else {}
    tail = f" Team report on this set: {off['final_resolution_success']} correct." if off else ""
    return "Case-by-case results are not in the repository yet." + tail


class RecordedSource:
    """Real predictions committed by the team (results/data on main). On the sets Run 1 never saw (red-team,
    combinations), B1 is computed here with the same code (it needs no GPU)."""

    def available(self, split: str) -> list[str]:
        return [k for k in GATES if self.preds(split, k) is not None]

    def preds(self, split: str, key: str, noisy: bool = False) -> dict | None:
        if split in D.EXTRA_SPLITS and key == "b1_rules" and not noisy and D.predictions(split, key) is None:
            return _b1_on(split)
        return D.predictions(split, key, noisy)

    def run(self, split: str, key: str, case_id: str, noisy: bool = False) -> GateRun:
        g = GATES[key]
        base = self.preds(split, key)
        if base is None:
            if key in (FINAL, B5_FINAL):
                return GateRun(g, None, "recorded", _pending_note(key, split))
            if key == "b5_v3_combo_gateexp" and split == "test":
                return GateRun(g, None, "recorded", "Not run on test: replaced by the final design before the test run.")
            where = D.SPLITS[split].split(" ·")[0].lower()
            return GateRun(g, None, "recorded", f"Not run on the {where}.")
        preds, note = base, None
        if noisy:
            nz = D.predictions(split, key, True)
            if nz is not None:
                preds = nz
            else:
                note = "No confusing-reply run for this gate; showing the normal reply."
        if case_id not in preds:
            return GateRun(g, None, "recorded", "Not scored here: the case starts after an answered question, and a "
                                               "yes/no gate has no question rounds.")
        live_b1 = key == "b1_rules" and split in D.EXTRA_SPLITS and D.predictions(split, key) is None
        return GateRun(g, preds[case_id], "live" if live_b1 else "recorded", note)

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


@st.cache_resource(show_spinner="Running the rules gate on the red-team set…")
def _b1_on(split: str) -> dict:
    return {cid: live.run(split, cid).trace for cid in D.cases(split)}


recorded = RecordedSource()
live = LiveRulesSource()


def newest(split: str) -> str:
    """The newest gate with case-by-case results on this set: the final system once its files are committed,
    otherwise the latest earlier version that ran on this set."""
    for k in (FINAL,) + HISTORY:
        if recorded.preds(split, k) is not None:
            return k
    return "b1_rules"


def reports(split: str) -> dict[str, dict]:
    """Every gate's metrics on this split, all against the same labels (see data.reports)."""
    out = dict(D.reports(split))
    if split in D.EXTRA_SPLITS and "b1_rules" not in out:      # Run 1 never saw these sets: B1 is computed live
        from sagate.eval import metrics as M

        out["b1_rules"] = {k: (str(v) if not isinstance(v, (int, float, dict)) else v)
                           for k, v in M.compute(_b1_on(split).values(), D.cases(split).values()).items()}
    return out
