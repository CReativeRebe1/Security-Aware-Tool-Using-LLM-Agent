from secgate.data.cases import Case
from secgate.eval.metrics import gold_metrics, macro_f1, noise_induced_errors
from secgate.gate.schema import GateInput


def _case(cid, gold, final, cat="benign"):
    gi = GateInput(case_id=cid, suite="banking", request={}, action={"function": "send_money"})
    return Case(input=gi, pool="test", category=cat, gold_decision=gold, gold_final_action=final,
                gold_missing_evidence="none", gold_required_authority="current_user")


def _pred(cid, first, final, inter=0, noisy=False):
    return {"case_id": cid, "first_decision": first, "final_decision": final, "interactions": inter,
            "noisy_response": noisy,
            "rounds": [{"output": {"decision": first, "missing_evidence": "none",
                                   "required_authority": "current_user"}}]}


def test_primary_metrics_on_toy_cases():
    cases = [_case("a", "ALLOW", "ALLOW"), _case("b", "BLOCK", "BLOCK"), _case("c", "ASK_USER", "ALLOW"),
             _case("d", "ESCALATE", "BLOCK"), _case("e", "BLOCK", "BLOCK", "authority_spoofing")]
    preds = [_pred("a", "ALLOW", "ALLOW"), _pred("b", "ASK_USER", "ALLOW", 1), _pred("c", "ASK_USER", "ALLOW", 1),
             _pred("d", "ESCALATE", "BLOCK", 1), _pred("e", "ALLOW", "ALLOW")]
    m = gold_metrics(preds, cases)
    assert str(m["final_resolution_success"]) == "3/5 (60.0%)"
    assert (m["unauthorized_action_rate"].k, m["unauthorized_action_rate"].n) == (2, 3)   # b and e executed
    assert (m["unnecessary_deferral_rate"].k, m["unnecessary_deferral_rate"].n) == (1, 3)
    assert m["mean_interactions"] == 0.6
    assert str(m["authority_spoofing_success"]) == "1/1 (100.0%)"
    assert (m["clarification_success"].k, m["clarification_success"].n) == (1, 1)
    assert (m["binary_unauthorized_rate"].k, m["binary_unauthorized_rate"].n) == (1, 3)


def test_macro_f1_and_noise():
    assert macro_f1(["a", "b"], ["a", "b"], ["a", "b", "c"]) == 1.0
    assert macro_f1(["a", "a"], ["a", "b"], ["a", "b"]) == (2 / 3 + 0) / 2
    cases = [_case("a", "ASK_USER", "ALLOW"), _case("b", "ASK_USER", "BLOCK")]
    clean = [_pred("a", "ASK_USER", "ALLOW", 1), _pred("b", "ASK_USER", "BLOCK", 1)]
    noisy = [_pred("a", "ASK_USER", "BLOCK", 1, noisy=True), _pred("b", "ASK_USER", "BLOCK", 1)]
    r = noise_induced_errors(clean, noisy, cases)
    assert (r.k, r.n) == (1, 1)
