#!/usr/bin/env python3
"""Local server for the labelling tool.

    python labeling_app/server.py            # then open http://localhost:8080

Serves the page and a small JSON API. Votes are written to
data/synthetic_data/batches/annotations/<annotator>/<batch_id>.json (see labels.py). The server enforces the
protocol: you can only write your own votes, only in batches you are assigned to, and as tie-breaker only on
disputed cases; primary annotators never receive anyone else's votes.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labels as L  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
CASE_FIELDS = ("case_id", "suite", "category", "difficulty", "round", "case_text")


def _case_view(c: dict) -> dict:
    """What the page needs: metadata, the rendered text and the evidence (never any stored labels)."""
    return {**{k: c.get(k) for k in CASE_FIELDS}, "input": (c.get("raw_case") or {}).get("input", {})}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def log_message(self, fmt, *args):          # keep the console quiet except for errors
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    # --- plumbing ------------------------------------------------------------------------------------------
    def _json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, msg, status=HTTPStatus.BAD_REQUEST):
        self._json({"error": msg}, status)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        routes = {"/api/config": self.config, "/api/batches": self.batches, "/api/batch": self.batch,
                  "/api/policies": self.policies}
        if u.path in routes:
            try:
                routes[u.path](q)
            except L.LabelError as e:
                self._fail(str(e))
            return
        if u.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/api/vote":
            return self._fail("not found", HTTPStatus.NOT_FOUND)
        try:
            n = int(self.headers.get("Content-Length", 0))
            self.vote(json.loads(self.rfile.read(n).decode("utf-8")))
        except (L.LabelError, json.JSONDecodeError) as e:
            self._fail(str(e))

    def _annotator(self, q) -> str:
        a = (q.get("annotator") or "").strip().lower()
        if a not in self.server.assignments["annotators"]:
            raise L.LabelError(f"unknown annotator {a!r}")
        return a

    # --- API -----------------------------------------------------------------------------------------------
    def config(self, q):
        a = self.server.assignments
        self._json({"annotators": a["annotators"], "rule": a.get("rule", ""),
                    "vocab": {"decision": L.DECISIONS, "final_action": L.FINAL_ACTIONS,
                              "missing_evidence": L.MISSING_EVIDENCE, "required_authority": L.REQUIRED_AUTHORITY}})

    def batches(self, q):
        """Every batch with the caller's role and progress."""
        ann, asg = self._annotator(q), self.server.assignments
        out = []
        for bid in sorted(asg["batches"]):
            role = L.role_of(asg, ann, bid)
            mine = L.read_votes(ann, bid) if role else {}
            row = {"batch_id": bid, "role": role, "done": sum(L.is_complete(v) for v in mine.values())}
            if role == "tiebreak":
                row["total"] = len(L.disputed_cases(asg, bid))
            elif role == "primary":
                row["total"] = 100
            out.append(row)
        self._json(out)

    def batch(self, q):
        ann, bid, asg = self._annotator(q), q.get("id", ""), self.server.assignments
        role = L.role_of(asg, ann, bid)
        if role is None:
            raise L.LabelError(f"{ann} is not assigned to {bid}")
        cases = L.load_batch(bid)
        others = {}
        if role == "tiebreak":
            others = L.disputed_cases(asg, bid)
            cases = [c for c in cases if c["case_id"] in others]
        self._json({"batch_id": bid, "role": role, "cases": [_case_view(c) for c in cases],
                    "votes": L.read_votes(ann, bid), "others": others})

    def policies(self, q):
        self._json(L.load_policies())

    def vote(self, body):
        ann, bid, cid = self._annotator(body), body.get("batch_id", ""), body.get("case_id", "")
        asg = self.server.assignments
        role = L.role_of(asg, ann, bid)
        if role is None:
            raise L.LabelError(f"{ann} is not assigned to {bid}")
        if cid not in self.server.case_ids(bid):
            raise L.LabelError(f"{cid} is not in {bid}")
        if role == "tiebreak" and cid not in L.disputed_cases(asg, bid):
            raise L.LabelError("tie-break votes are only taken on disputed cases")
        votes = L.write_vote(ann, bid, cid, body.get("vote"), role)
        self._json({"ok": True, "complete": L.is_complete(votes.get(cid)),
                    "done": sum(L.is_complete(v) for v in votes.values())})


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr):
        super().__init__(addr, Handler)
        self.assignments = L.load_assignments()
        self._ids: dict[str, set] = {}

    def case_ids(self, bid: str) -> set:
        if bid not in self._ids:
            self._ids[bid] = {c["case_id"] for c in L.load_batch(bid)}
        return self._ids[bid]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    for port in range(a.port, a.port + 20):
        try:
            httpd = Server(("127.0.0.1", port))
        except OSError:
            continue
        print(f"Labelling tool: http://localhost:{port}   (Ctrl+C to stop)")
        print(f"Votes are saved under {L.ANNOTATIONS_DIR}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        httpd.server_close()
        return
    sys.exit("no free port found")


if __name__ == "__main__":
    main()
