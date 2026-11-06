"""End-to-end checks of the two-reviewer protocol: the real server on a temporary annotations folder."""

import json
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "labeling_app"))
import labels as L  # noqa: E402
import merge  # noqa: E402
import server  # noqa: E402

BATCH = "batch_01"


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "ANNOTATIONS_DIR", tmp_path / "annotations")
    monkeypatch.setattr(L, "LABELS_DIR", tmp_path / "labels")
    httpd = server.Server(("127.0.0.1", 0))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    yield call
    httpd.shutdown()
    httpd.server_close()


def vote(decision, final=None, missing="none", authority="current_user", status="edited", **kw):
    v = {"gold_decision": decision, "gold_final_action": final or decision, "gold_missing_evidence": missing,
         "gold_required_authority": authority, "gold_clause_ids": [], "notes": "",
         "review": {"status": status, "explanation": "because"}}
    v.update(kw)
    return v


def cant(reason="no_option_fits", note="two actions in one call"):
    return {"gold_decision": None, "gold_final_action": None, "gold_missing_evidence": None,
            "gold_required_authority": None, "gold_clause_ids": [], "user_response": None, "notes": note,
            "review": {"status": "cannot_label", "reason": reason, "note": note}}


def test_every_batch_has_exactly_two_reviewers():
    asg = L.load_assignments()
    load = Counter()
    for b in asg["batches"].values():
        assert len(b["reviewers"]) == 2 and len(set(b["reviewers"])) == 2
        load.update(b["reviewers"])
    assert set(load) == set(asg["annotators"]) and len(set(load.values())) == 1     # equal share each


def test_two_phases_of_five_batches_each():
    asg = L.load_assignments()
    for ph in L.PHASES:
        bids = L.phase_batches(asg, ph)
        assert len(bids) == 10
        load = Counter(r for b in bids for r in asg["batches"][b]["reviewers"])
        assert load == Counter({n: 5 for n in asg["annotators"]})
    assert sorted(L.phase_batches(asg, 1) + L.phase_batches(asg, 2)) == sorted(asg["batches"])


def test_unequal_phase_is_rejected(tmp_path, monkeypatch):
    a = json.loads(L.ASSIGNMENTS_FILE.read_text(encoding="utf-8"))
    one = next(b for b, v in a["batches"].items() if v["phase"] == 1)
    a["batches"][one]["phase"] = 2
    bad = tmp_path / "assignments.json"
    bad.write_text(json.dumps(a), encoding="utf-8")
    monkeypatch.setattr(L, "ASSIGNMENTS_FILE", bad)
    with pytest.raises(L.LabelError):
        L.load_assignments()


def test_protocol_end_to_end(srv):
    asg = L.load_assignments()
    a, b = asg["batches"][BATCH]["reviewers"]
    outsiders = [n for n in asg["annotators"] if n not in (a, b)]
    assert outsiders

    st, cfg = srv("/api/config")
    assert st == 200 and set(cfg["annotators"]) == {a, b, *outsiders}
    st, d = srv(f"/api/batch?id={BATCH}&annotator={a}")
    assert st == 200 and len(d["cases"]) == 100 and set(d) == {"batch_id", "cases", "votes"}
    assert "gold_decision" not in json.dumps(d["cases"][0])          # cases never carry stored labels
    ids = [c["case_id"] for c in d["cases"]]

    # suggestions: only for the batch's reviewers, only that batch's cases
    st, sg = srv(f"/api/suggestions?id={BATCH}&annotator={a}")
    assert st == 200 and sg and set(sg) <= set(ids)
    assert next(iter(sg.values()))["explanation"]

    # a third person cannot read, get suggestions or write; unknown names and bad values are rejected
    for o in outsiders:
        assert srv(f"/api/batch?id={BATCH}&annotator={o}")[0] == 400
        assert srv(f"/api/suggestions?id={BATCH}&annotator={o}")[0] == 400
        assert srv("/api/vote", {"annotator": o, "batch_id": BATCH, "case_id": ids[0], "vote": vote("ALLOW")})[0] == 400
    assert srv("/api/vote", {"annotator": "mallory", "batch_id": BATCH, "case_id": ids[0], "vote": vote("ALLOW")})[0] == 400
    assert srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": ids[0], "vote": vote("MAYBE")})[0] == 400
    assert srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": ids[0],
                             "vote": vote("ALLOW", final="BLOCK")})[0] == 400
    assert srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": ids[0],
                             "vote": cant(note="  ")})[0] == 400                      # can't-label needs a note
    assert srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": ids[0],
                             "vote": vote("ALLOW", review={"status": "accepted"})})[0] == 400  # needs explanation

    # concurrent saves of many cases by the same reviewer: none is lost
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda cid: srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": cid,
                                                   "vote": vote("ALLOW", status="accepted")}), ids[:40]))
    assert len(L.read_votes(a, BATCH)) == 40

    # case 0 agreed, 1 disputed, 2 incomplete ASK_USER, 3 both can't label, 4 only one can't label
    srv("/api/vote", {"annotator": b, "batch_id": BATCH, "case_id": ids[0], "vote": vote("ALLOW")})
    srv("/api/vote", {"annotator": b, "batch_id": BATCH, "case_id": ids[1], "vote": vote("BLOCK", authority="none")})
    srv("/api/vote", {"annotator": b, "batch_id": BATCH, "case_id": ids[2],
                      "vote": vote("ASK_USER", final="ALLOW", missing="recipient_identity")})
    assert srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": ids[3], "vote": cant()})[0] == 200
    srv("/api/vote", {"annotator": b, "batch_id": BATCH, "case_id": ids[3], "vote": cant("unclear_request")})
    srv("/api/vote", {"annotator": b, "batch_id": BATCH, "case_id": ids[4], "vote": cant()})

    # reviewers are blind: a's view holds only a's reviews
    st, d = srv(f"/api/batch?id={BATCH}&annotator={a}")
    assert d["votes"][ids[1]]["gold_decision"] == "ALLOW" and all(v["annotator"] == a for v in d["votes"].values())
    assert set(L.read_votes(b, BATCH)) == set(ids[:5])

    st, rows = srv(f"/api/batches?annotator={b}")
    row = next(r for r in rows if r["batch_id"] == BATCH)
    assert row["reviewer"] is True and row["total"] == 100 and row["done"] == 4      # ids[2] is incomplete
    st, rows = srv(f"/api/batches?annotator={outsiders[0]}")
    assert next(r for r in rows if r["batch_id"] == BATCH)["reviewer"] is False

    merge.main()
    ph = asg["batches"][BATCH]["phase"]
    out = L.LABELS_DIR / "combined"
    cases = {json.loads(x)["case_id"]: json.loads(x) for x in open(out / "cases.jsonl", encoding="utf-8")}
    assert len(cases) == 2000 and cases[ids[0]]["phase"] == ph
    assert cases[ids[0]]["status"] == "agreed" and cases[ids[0]]["gold_decision"] == "ALLOW"
    assert cases[ids[0]]["reviewers"] == [a, b]
    assert cases[ids[1]]["status"] == "disputed"
    assert cases[ids[2]]["status"] == "partial"
    assert cases[ids[3]]["status"] == "cannot_label"
    assert cases[ids[4]]["status"] == "disputed"
    assert cases[ids[50]]["status"] == "unlabeled"
    gold = [json.loads(x)["case_id"] for x in open(out / "gold.jsonl", encoding="utf-8")]
    assert gold == [ids[0]]
    disputed = json.loads((out / "disputed.json").read_text())
    assert sorted(sum(disputed.values(), [])) == sorted([ids[1], ids[4]])
    cl = json.loads((out / "cannot_label.json").read_text(encoding="utf-8"))
    assert cl[BATCH][0]["case_id"] == ids[3] and cl[BATCH][0]["reasons"][b]["reason"] == "unclear_request"
    agreement = json.loads((out / "agreement.json").read_text())
    assert agreement["gold_decision"]["n_cases"] == 2

    # per phase: this batch's phase has the same results; the other phase has none of its cases
    mine = L.LABELS_DIR / f"phase_{ph}"
    other = L.LABELS_DIR / f"phase_{3 - ph}"
    assert [json.loads(x)["case_id"] for x in open(mine / "gold.jsonl", encoding="utf-8")] == [ids[0]]
    assert sum(1 for _ in open(mine / "cases.jsonl", encoding="utf-8")) == 1000
    assert open(other / "gold.jsonl", encoding="utf-8").read() == ""
    summary = json.loads((L.LABELS_DIR / "summary.json").read_text())
    assert summary[f"phase_{ph}"]["agreed"] == 1 and summary[f"phase_{ph}"]["finished"] is False
    assert json.loads((mine / "label_mix.json").read_text())["gold_decision"] == {"ALLOW": 1}


def test_resolution_rules():
    def r(d, f, ann, **kw):
        return {**vote(d, f, **kw), "annotator": ann}

    def c(ann):
        return {**cant(), "annotator": ann}

    assert L.resolve(None, None)[0] == "unlabeled"
    assert L.resolve(r("ALLOW", None, "a"), None)[0] == "partial"
    st, g = L.resolve(r("ESCALATE", "ALLOW", "a", missing="approval", authority="manager"),
                      r("ESCALATE", "ALLOW", "b", missing="approval", authority="manager"))
    assert st == "agreed" and g["gold_decision"] == "ESCALATE" and g["annotators"] == ["a", "b"]
    assert L.resolve(r("ALLOW", None, "a"), r("BLOCK", None, "b"))[0] == "disputed"
    # same decision but different final action is a dispute too
    assert L.resolve(r("ASK_USER", "ALLOW", "a", user_response={"text": "yes", "confirmed": True}),
                     r("ASK_USER", "BLOCK", "b", user_response={"text": "no", "confirmed": False}))[0] == "disputed"
    assert L.resolve(c("a"), c("b"))[0] == "cannot_label"
    assert L.resolve(c("a"), r("ALLOW", None, "b"))[0] == "disputed"


def test_alpha_and_kappa():
    assert merge.krippendorff_alpha([["a", "a"], ["b", "b"], ["a", "a"]]) == 1.0
    assert merge.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert merge.krippendorff_alpha([["a", "b"], ["b", "a"]]) < 0


def test_policies_parse():
    pol = L.load_policies()
    assert len(pol) == 42 and all(p["id"] and p["title"] and p["text"] for p in pol)
