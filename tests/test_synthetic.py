import json

import pytest

from sagate.data.cases import Case, save_cases
from sagate.data.splits import Splits
from sagate.evidence.policy_rag import parse_handbook
from sagate.resolution.responders import MockApprover
from sagate.train.nl_examples import load_nl_examples
from sagate.train.synthetic import (Env, SpecError, build, build_realization, load_specs, merge,
                                    validate_realization)


@pytest.fixture(scope="module")
def built():
    return build(2000, write=False)


@pytest.fixture(scope="module")
def valid_clauses(cfg):
    return {c.id for s in ("workspace", "banking") for c in parse_handbook(cfg.resources_dir / "handbooks" / f"{s}.md")}


def test_specs_are_valid():
    reals = load_specs()
    assert len({r.family for r in reals}) >= 100
    assert [e for r in reals for e in validate_realization(r)] == []


def test_cases_are_unlabeled_train_decision_only(built, data):
    splits = Splits(data)
    ids = [b.case.case_id for b in built]
    assert len(ids) == len(set(ids)) == 2000
    for b in built:
        c = b.case
        assert c.pool == "train" and c.subset == "decision_only" and c.scenario_id is None
        assert not c.has_gold and c.gold_clause_ids is None
        splits.assert_pool(c, "train_only")


def test_design_key_is_complete(built):
    for b in built:
        k = b.key
        assert k["decision"] in ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")
        assert k["final"] in ("ALLOW", "BLOCK"), k["case_id"]
        if k["decision"] in ("ALLOW", "BLOCK"):
            assert k["final"] == k["decision"]


def test_injection_cases_carry_untrusted_provenance(built):
    for b in built:
        if b.case.category == "injection" and b.key["round"] == 0:
            prov = b.case.input.provenance
            assert any(p.get("trust") == "untrusted" for p in prov), b.case.case_id


def test_resolution_rounds_are_recorded(built):
    later = [b for b in built if b.key["round"] == 1]
    assert later
    for b in later:
        h = b.case.input.resolution_history
        assert len(h) == 1 and h[0]["kind"] in ("ASK_USER", "ESCALATE")
    # a user's own "approval" never counts as authority: those rounds keep the escalation
    over = [b for b in later if b.case.meta.get("resolution") == "user_overreach"]
    assert over and all(b.key["decision"] == "ESCALATE" for b in over)


def test_escalation_final_follows_mock_approver(cfg, builder, data, valid_clauses):
    r = next(x for x in load_specs() if x.family == "ws-share-product-dev-plan" and x.variant == "external-partner")
    b = build_realization(r, builder, Env(data), valid_clauses, MockApprover(cfg.resources_dir))[0]
    assert b.key["decision"] == "ESCALATE" and b.key["final"] == "BLOCK"   # resource owner denies external release


def test_unknown_extra_prompt_target_is_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text("[]")
    (tmp_path / "x_extra_prompts.yaml").write_text(json.dumps([{"family": "nope", "variant": "*", "prompts": ["hi"]}]))
    with pytest.raises(SpecError):
        load_specs(tmp_path)


def test_merge_produces_valid_nl_training_file(built, tmp_path):
    picked = [b for b in built if b.key["round"] == 0 and b.key["decision"] in ("ALLOW", "ESCALATE")][:6]
    cases_path, gold_path, out = tmp_path / "cases.jsonl", tmp_path / "gold.jsonl", tmp_path / "synthetic_nl.jsonl"
    save_cases(cases_path, [b.case for b in picked])
    gold = [{"case_id": b.key["case_id"], "gold_decision": b.key["decision"], "gold_final_action": b.key["final"],
             "gold_missing_evidence": b.key["missing_evidence"], "gold_required_authority": b.key["required_authority"],
             "gold_clause_ids": b.key["clauses"]} for b in picked[:4]]
    gold_path.write_text("".join(json.dumps(g) + "\n" for g in gold))
    assert merge(cases_path, gold_path, out, reviewer="member_b") == 4
    cases = load_nl_examples(out)
    assert len(cases) == 4 and all(isinstance(c, Case) and c.meta["reviewed_by"] == "member_b" for c in cases)
