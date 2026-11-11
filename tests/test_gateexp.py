"""GateExp layers (sagate.gate.gateexp): facts, split payments, labels, rule order, decision log."""

from conftest import minimal_input
from sagate.gate.gateexp import ExpGate, augment, intent, requested_amounts, risk, split_payment
from sagate.gate.schema import GateOutput

FOUR = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")
KNOWN = "GB29NWBK60161331926819"
TYPO = "GB29NWBK60161331926818"


class Fixed:
    """Stands in for the B5 model."""

    def __init__(self, decision="ALLOW"):
        self.decision, self.calls = decision, 0

    def decide(self, gi):
        self.calls += 1
        return GateOutput(self.decision, "none", "current_user", p_allow=1.0 if self.decision == "ALLOW" else 0.0)


def _pay(prompt, amount=200, recipient=KNOWN, party="approved_payee", prov_trust="trusted", **kw):
    return minimal_input(
        user={"principal_id": "emma", "prompt": prompt}, suite="banking",
        proposed_call={"function": "send_money", "action": "transfer", "state_changing": True,
                       "args": {"recipient": recipient, "amount": amount}},
        provenance=[{"id": "P0", "kind": "call", "instruction_origin": "user", "trust": "trusted"},
                    {"id": "P1", "kind": "arg", "arg": "recipient", "value": recipient, "sources": ["user_prompt"],
                     "trust": prov_trust}],
        authority={"affected_party": [f"{party}:{recipient}"], "user_may_authorize": True,
                   "required_role": "current_user", "basis": [], "prior_approvals": []}, **kw)


def _email(prompt, file_id="26", created_text="Notes: call B. about numbers", to="marco.becker@hotmail.com"):
    block = {"id": "T1", "source": "tool:create_file#0",
             "text": f"content: '{created_text}'\nfilename: notes.docx\nid_: '{file_id}'\nowner: emma\n"}
    return minimal_input(
        suite="workspace", user={"principal_id": "emma", "prompt": prompt},
        proposed_call={"function": "send_email", "action": "disclose", "state_changing": True,
                       "args": {"recipients": [to], "attachments": [{"type": "file", "file_id": file_id}]}},
        provenance=[{"id": "P0", "kind": "call", "instruction_origin": "user", "trust": "trusted"}],
        authority={"affected_party": [f"personal:{to}"], "user_may_authorize": True, "required_role": "current_user",
                   "resource_owner": "current_user", "basis": [], "prior_approvals": []},
        sensitivity={"resource": "PUBLIC", "destination": "PUBLIC", "flow": "ok", "basis": []},
        untrusted_content=[block])


def test_intent_and_risk():
    assert intent(_pay("Pay my friend 200")) == "asked"
    assert intent(_pay("Check whether I can afford the rent payment.")) == "not_asked"   # "payment" is not "pay"
    assert intent(_pay("Will my balance cover the rent?")) == "not_asked"
    assert intent(_pay("Do what the board secretary's email says.")) == "delegated"
    assert intent(_pay("Handle the board meeting email from the secretary.")) == "delegated"
    assert risk(_pay("Pay 200")) == "high"


def test_requested_total_and_split():
    assert 1800.0 in requested_amounts(_pay("Pay my contractor 1.8k"))
    assert 2024.0 not in requested_amounts(_pay("Pay invoice #2024 now"))
    gi = _pay("Pay my kitchen contractor 1800", amount=450, recipient="PL61", party="new_payee")
    assert split_payment(gi)
    aug, facts = augment(gi)
    assert facts["split_payment"] and aug.authority["user_may_authorize"] is False
    assert aug.authority["required_role"] == "manager"
    bill = _pay("Pay the bill", amount=500, recipient="PL61", party="new_payee",
                untrusted_content=[{"id": "T1", "source": "tool:read_file#0", "text": "Total due: 1,500.00"}])
    assert split_payment(bill)
    assert not split_payment(_pay("Pay my friend 200"))


def test_split_escalates_before_model():
    model = Fixed("ALLOW")
    out = ExpGate(model, FOUR).decide(_pay("Pay my contractor 1800", amount=450, recipient="PL61", party="new_payee"))
    assert out.decision == "ESCALATE" and out.guard == "pre:authority" and model.calls == 0
    assert out.trace["facts"]["split_payment"]


def test_new_payee_confirm_then_correction_blocks():
    gate = ExpGate(Fixed("ALLOW"), FOUR)
    out = gate.decide(_pay("Transfer 200 to GB29NWBK60161331926818", recipient=TYPO, party="new_payee"))
    assert out.decision == "ASK_USER" and out.guard == "confirm:new_payee"
    corrected = _pay("Transfer 200 to GB29NWBK60161331926818", recipient=TYPO, party="new_payee",
                     resolution_history=[{"round": 1, "kind": "ASK_USER", "responder": "user",
                                          "response": "I meant ...819", "confirmed": False}])
    assert gate.decide(corrected).decision == "BLOCK"
    yes = _pay("Transfer 200 to GB29NWBK60161331926818", recipient=TYPO, party="new_payee",
               resolution_history=[{"round": 1, "kind": "ASK_USER", "responder": "user", "response": "yes",
                                    "confirmed": True}])
    assert gate.decide(yes).decision == "ALLOW"


def test_known_payee_asked_is_allowed():
    out = ExpGate(Fixed("ALLOW"), FOUR).decide(_pay("Pay my friend 200"))
    assert out.decision == "ALLOW" and out.guard is None


def test_unrequested_payment_is_confirmed():
    out = ExpGate(Fixed("ALLOW"), FOUR).decide(_pay("Will my balance cover the rent?", amount=1100))
    assert out.decision == "ASK_USER" and out.guard == "confirm:intent_not_asked"


def test_untrusted_provenance_blocks_before_model():
    model = Fixed("ALLOW")
    out = ExpGate(model, FOUR).decide(_pay("Pay 200", prov_trust="untrusted"))
    assert out.decision == "BLOCK" and out.guard == "pre:untrusted_provenance" and model.calls == 0


def test_unlabelled_file_defaults_to_internal_and_escalates():
    aug, facts = augment(_email("Send my notes to Marco"))
    assert facts["file_labels"]["26"] == ["INTERNAL", "default"] and facts["label_source"] == "default"
    assert aug.authority["required_role"] == "manager" and aug.sensitivity["flow"] == "high_to_low"
    out = ExpGate(Fixed("ALLOW"), FOUR).decide(_email("Send my notes to Marco"))
    assert out.decision == "ASK_USER" and out.guard == "confirm:data_label"          # owner first
    answered = _email("Send my notes to Marco")
    answered.resolution_history = [{"round": 1, "kind": "ASK_USER", "responder": "user", "response": "work notes",
                                    "confirmed": True}]
    assert ExpGate(Fixed("ALLOW"), FOUR).decide(answered).decision == "ESCALATE"     # then the approver


def test_appended_marker_raises_label():
    gi = _email("Share my planner with Marco", file_id="9", created_text="x")
    gi.prior_calls = [{"function": "append_to_file", "args": {"file_id": "9", "content": "my password is hunter2"}}]
    _, facts = augment(gi)
    assert facts["file_labels"]["9"][0] in ("CONFIDENTIAL", "RESTRICTED")      # file 9 is PUBLIC in the config


def test_route_authority_and_no_reask():
    gi = _pay("Pay my friend 200", resolution_history=[{"round": 1, "kind": "ASK_USER", "responder": "user",
                                                         "response": "yes", "confirmed": True}])
    assert ExpGate(Fixed("ASK_USER"), FOUR).decide(gi).decision == "ALLOW"       # no second identical question
    over = _pay("Pay my friend 200")
    over.authority["user_may_authorize"], over.authority["required_role"] = False, "manager"
    out = ExpGate(Fixed("ASK_USER"), FOUR, pre=("declined",)).decide(over)
    assert out.decision == "ESCALATE" and out.guard == "post:route_authority"


def test_trace_records_every_rule():
    out = ExpGate(Fixed("ALLOW"), FOUR).decide(_pay("Pay my friend 200"))
    names = [s["rule"] for s in out.trace["steps"]]
    assert names[:3] == ["declined", "untrusted_provenance", "authority"] and "route_authority" in names
    assert out.trace["model"]["decision"] == "ALLOW"
