"""End-to-end checks of the labelling protocol: the real server on a temporary annotations folder."""

import json
import sys
import threading
import urllib.error
import urllib.request
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


def vote(decision, final=None, missing="none", authority="current_user", **kw):
    v = {"gold_decision": decision, "gold_final_action": final or decision, "gold_missing_evidence": missing,
         "gold_required_authority": authority, "gold_clause_ids": [], "notes": ""}
    v.update(kw)
    return v


def test_protocol_end_to_end(srv):
    asg = L.load_assignments()
    a, b = asg["batches"][BATCH]["primary"]
    tb = asg["batches"][BATCH]["tiebreak"]
    outsider = next(n for n in asg["annotators"] if L.role_of(asg, n, BATCH) is None)

    st, cfg = srv("/api/config")
    assert st == 200 and set(cfg["annotators"]) == {a, b, tb, outsider}
    st, d = srv(f"/api/batch?id={BATCH}&annotator={a}")
    assert st == 200 and d["role"] == "primary" and len(d["cases"]) == 100 and d["others"] == {}
    assert "gold_decision" not in json.dumps(d["cases"][0])          # cases never carry stored labels
    ids = [c["case_id"] for c in d["cases"]]

    # outsiders and unknown names cannot read or write; bad values are rejected
    assert srv(f"/api/batch?id={BATCH}&annotator={outsider}")[0] == 400
    assert srv("/api/vote", {"annotator": outsider, "batch_id": BATCH, "case_id": ids[0], "vote": vote("ALLOW")})[0] == 400
    assert srv("/api/vote", {"annotator": "mallory", "batch_id": BATCH, "case_id": ids[0], "vote": vote("ALLOW")})[0] == 400
    assert srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": ids[0], "vote": vote("MAYBE")})[0] == 400
    assert srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": ids[0],
                             "vote": vote("ALLOW", final="BLOCK")})[0] == 400

    # concurrent saves of many cases by the same annotator: none is lost
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda cid: srv("/api/vote", {"annotator": a, "batch_id": BATCH, "case_id": cid,
                                                   "vote": vote("ALLOW")}), ids[:40]))
    assert len(L.read_votes(a, BATCH)) == 40

    # case 0 agreed, case 1 disputed, case 2 one ASK_USER vote missing its reply (incomplete)
    srv("/api/vote", {"annotator": b, "batch_id": BATCH, "case_id": ids[0], "vote": vote("ALLOW")})
    srv("/api/vote", {"annotator": b, "batch_id": BATCH, "case_id": ids[1], "vote": vote("BLOCK", authority="none")})
    srv("/api/vote", {"annotator": b, "batch_id": BATCH, "case_id": ids[2],
                      "vote": vote("ASK_USER", final="ALLOW", missing="recipient_identity")})

    # primaries are blind: a's view never contains b's votes
    st, d = srv(f"/api/batch?id={BATCH}&annotator={a}")
    assert d["votes"][ids[1]]["gold_decision"] == "ALLOW" and d["others"] == {}

    # tie-breaker sees only the disputed case, with both votes, and may vote only there
    st, d = srv(f"/api/batch?id={BATCH}&annotator={tb}")
    assert d["role"] == "tiebreak" and [c["case_id"] for c in d["cases"]] == [ids[1]]
    assert {v["annotator"] for v in d["others"][ids[1]]} == {a, b}
    assert srv("/api/vote", {"annotator": tb, "batch_id": BATCH, "case_id": ids[0], "vote": vote("BLOCK")})[0] == 400
    assert srv("/api/vote", {"annotator": tb, "batch_id": BATCH, "case_id": ids[1],
                             "vote": vote("BLOCK", authority="none")})[0] == 200

    # a vote is stored under its author's name only; b's file is untouched by a's saves
    assert all(v["annotator"] == a for v in L.read_votes(a, BATCH).values())
    assert set(L.read_votes(b, BATCH)) == set(ids[:3])

    st, rows = srv(f"/api/batches?annotator={tb}")
    row = next(r for r in rows if r["batch_id"] == BATCH)
    assert row["role"] == "tiebreak" and row["total"] == 1 and row["done"] == 1

    merge.main()
    cases = {json.loads(x)["case_id"]: json.loads(x) for x in open(L.LABELS_DIR / "cases.jsonl", encoding="utf-8")}
    assert cases[ids[0]]["status"] == "agreed" and cases[ids[0]]["gold_decision"] == "ALLOW"
    assert cases[ids[1]]["status"] == "resolved" and cases[ids[1]]["gold_decision"] == "BLOCK"
    assert cases[ids[1]]["gold_required_authority"] == "none"
    assert cases[ids[2]]["status"] == "partial"
    assert cases[ids[50]]["status"] == "unlabeled"
    agreement = json.loads((L.LABELS_DIR / "agreement.json").read_text())
    assert agreement["gold_decision"]["n_cases"] == 2


def test_resolution_rules():
    p = lambda d, f, ann, **kw: {**vote(d, f, **kw), "annotator": ann, "role": "primary"}  # noqa: E731
    t = lambda d, f, **kw: {**vote(d, f, **kw), "annotator": "t", "role": "tiebreak"}  # noqa: E731
    assert L.resolve([p("ESCALATE", "ALLOW", "a", missing="approval", authority="manager"),
                      p("ESCALATE", "ALLOW", "b", missing="approval", authority="manager")], None)[0] == "agreed"
    assert L.resolve([p("ALLOW", None, "a"), p("BLOCK", None, "b")], None)[0] == "awaiting_tiebreak"
    st, g = L.resolve([p("ALLOW", None, "a"), p("BLOCK", None, "b", authority="none")], t("BLOCK", None, authority="none"))
    assert st == "resolved" and g["gold_decision"] == "BLOCK" and set(g["annotators"]) == {"a", "b", "t"}
    assert L.resolve([p("ALLOW", None, "a"), p("BLOCK", None, "b")], t("ESCALATE", "BLOCK"))[0] == "unresolved"
    # same decision but different final action is a dispute too
    assert L.resolve([p("ASK_USER", "ALLOW", "a", user_response={"text": "yes", "confirmed": True}),
                      p("ASK_USER", "BLOCK", "b", user_response={"text": "no", "confirmed": False})],
                     None)[0] == "awaiting_tiebreak"


def test_alpha_and_kappa():
    assert merge.krippendorff_alpha([["a", "a"], ["b", "b"], ["a", "a"]]) == 1.0
    assert merge.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert merge.krippendorff_alpha([["a", "b"], ["b", "a"]]) < 0


def test_policies_parse():
    pol = L.load_policies()
    assert len(pol) == 42 and all(p["id"] and p["title"] and p["text"] for p in pol)
