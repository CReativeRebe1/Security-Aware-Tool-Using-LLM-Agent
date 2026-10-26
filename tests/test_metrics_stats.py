from conftest import minimal_input
from sagate.data.cases import Case
from sagate.eval.metrics import Rate, compute, macro_f1, noise_induced_errors
from sagate.eval.stats import (cohen_kappa, holm, krippendorff_alpha_nominal, mcnemar_exact, paired_bootstrap)
from sagate.models.chat import parse_tool_calls


def _case(cid, gold_decision, gold_final, category=None):
    c = Case(input=minimal_input(case_id=cid), pool="test", category=category)
    c.gold_decision, c.gold_final_action = gold_decision, gold_final
    c.gold_missing_evidence, c.gold_required_authority = "none", "current_user"
    return c


def _pred(cid, first, final, interactions=0):
    return {"case_id": cid, "first_decision": first, "final_decision": final, "interactions": interactions,
            "rounds": [{"output": {"decision": first, "missing_evidence": "none", "required_authority": "current_user"}}]}


def test_metrics_on_toy_cases():
    cases = [_case("a", "ALLOW", "ALLOW"), _case("b", "BLOCK", "BLOCK"), _case("c", "ASK_USER", "ALLOW"),
             _case("d", "ESCALATE", "BLOCK"), _case("e", "BLOCK", "BLOCK", "authority_spoofing")]
    preds = [_pred("a", "ASK_USER", "ALLOW", 1),        # unnecessary deferral, still success
             _pred("b", "ALLOW", "ALLOW"),              # unauthorized
             _pred("c", "ASK_USER", "ALLOW", 1),        # clarification success
             _pred("d", "ESCALATE", "BLOCK", 1),        # escalation correct
             _pred("e", "BLOCK", "BLOCK")]
    m = compute(preds, cases)
    assert m["n"] == 5
    assert (m["final_resolution_success"].k, m["final_resolution_success"].n) == (4, 5)
    assert (m["unauthorized_action_rate"].k, m["unauthorized_action_rate"].n) == (1, 3)
    assert (m["unnecessary_deferral_rate"].k, m["unnecessary_deferral_rate"].n) == (1, 3)
    assert (m["clarification_success"].k, m["clarification_success"].n) == (1, 1)
    assert (m["escalation_precision"].k, m["escalation_precision"].n) == (1, 1)
    assert (m["authority_spoofing_success"].k, m["authority_spoofing_success"].n) == (0, 1)
    assert abs(m["mean_interactions"] - 0.6) < 1e-9
    assert str(Rate(3, 61)) == "3/61 (4.9%)"


def test_noise_induced_errors():
    cases = [_case("a", "ASK_USER", "ALLOW"), _case("b", "ASK_USER", "ALLOW")]
    clean = [_pred("a", "ASK_USER", "ALLOW", 1), _pred("b", "ASK_USER", "ALLOW", 1)]
    noisy = [dict(_pred("a", "ASK_USER", "BLOCK", 1), noisy_response=True), _pred("b", "ASK_USER", "ALLOW", 1)]
    r = noise_induced_errors(clean, noisy, cases)
    assert (r.k, r.n) == (1, 1)


def test_macro_f1():
    assert macro_f1(["a", "b"], ["a", "b"]) == 1.0
    assert abs(macro_f1(["a", "a", "b"], ["a", "b", "b"]) - (2 / 3 + 2 / 3) / 2) < 1e-9


def test_stats():
    a, b = [1] * 30 + [0] * 10, [1] * 20 + [0] * 20
    bs = paired_bootstrap(a, b, n_resamples=2000)
    assert abs(bs["diff"] - 0.25) < 1e-9 and bs["ci_low"] < 0.25 < bs["ci_high"]
    mc = mcnemar_exact([True] * 10 + [False] * 2, [False] * 10 + [True] * 2)
    assert mc["b01"] == 10 and mc["b10"] == 2 and 0.03 < mc["p_value"] < 0.04
    adj = holm({"x": 0.01, "y": 0.04, "z": 0.03})
    assert adj["x"]["p_holm"] == 0.03 and adj["y"]["p_holm"] == 0.06 and adj["x"]["reject"]
    assert cohen_kappa(list("aabb"), list("aabb")) == 1.0
    # Krippendorff (2011) worked example is complex; check perfect + chance-level behaviour
    assert krippendorff_alpha_nominal([["a", "a"], ["b", "b"], ["c", "c"]]) == 1.0
    assert krippendorff_alpha_nominal([["a", "b"], ["b", "a"]]) < 0


def test_parse_qwen_tool_calls():
    text = ('Let me check.\n<tool_call>\n{"name": "send_money", "arguments": {"recipient": "X", "amount": 5}}\n'
            '</tool_call>\n<tool_call>\n{"name": "get_balance", "arguments": {}}\n</tool_call>')
    content, calls, err = parse_tool_calls(text)
    assert err is None and content == "Let me check."
    assert calls == [{"function": "send_money", "args": {"recipient": "X", "amount": 5}},
                     {"function": "get_balance", "args": {}}]
    _, calls, err = parse_tool_calls('<tool_call>\n{"name": "x", "arguments": {bad json}\n</tool_call>')
    assert err and calls == []


def test_binary_projection_metrics(make_case):
    from sagate.eval.metrics import compute
    c1 = make_case("banking", "x", {"function": "send_money", "args": {"recipient": "a", "amount": 1}})
    c1.gold_decision, c1.gold_final_action = "ASK_USER", "ALLOW"
    pred = {"case_id": c1.case_id, "first_decision": "ASK_USER", "final_decision": "ALLOW", "interactions": 1,
            "rounds": [{"round": 0, "output": {}}]}
    m = compute([pred], [c1])
    assert m["final_resolution_success"].k == 1 and m["binary_success"].k == 0
