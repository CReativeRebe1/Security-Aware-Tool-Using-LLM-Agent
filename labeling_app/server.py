#!/usr/bin/env python3
"""Lightweight local server for the Synthetic Data Human Labelling Interface.

Run with:
    python3 labeling_app/server.py
or
    python3 -m labeling_app.server --port 8080
"""

import csv
import json
import os
import sqlite3
import sys
import urllib.parse
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Paths
ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
BATCHES_DIR = ROOT_DIR / "data" / "synthetic_data" / "batches"
ANNOTATIONS_DIR = BATCHES_DIR / "annotations"
MANIFEST_FILE = BATCHES_DIR / "manifest.json"
DB_FILE = ANNOTATIONS_DIR / "annotations.db"

ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)


def init_db():
    """Initialize local SQLite database for annotations."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            case_id TEXT PRIMARY KEY,
            batch_id TEXT,
            annotator TEXT,
            gold_decision TEXT,
            gold_final_action TEXT,
            gold_missing_evidence TEXT,
            gold_required_authority TEXT,
            gold_clause_ids TEXT,
            user_response_text TEXT,
            user_response_confirmed TEXT,
            notes TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()

LABEL_COLUMNS = [
    "gold_decision",
    "gold_final_action",
    "gold_missing_evidence",
    "gold_required_authority",
    "gold_clause_ids",
    "user_response_text",
    "user_response_confirmed",
    "user_response_noisy_text",
    "user_response_noisy_confirmed",
    "notes",
]


class LabelingServerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if path == "/api/manifest":
            self.handle_get_manifest(params)
        elif path == "/api/batch":
            self.handle_get_batch(params)
        elif path == "/api/export":
            self.handle_export_csv(params)
        elif path == "/api/stats":
            self.handle_get_stats(params)
        else:
            # Fall back to static files in APP_DIR
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/save":
            self.handle_post_save()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint not found")

    def _send_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_get_manifest(self, params):
        if not MANIFEST_FILE.exists():
            self._send_json({"error": "manifest.json not found. Run prepare_batches.py first."}, status=404)
            return

        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        annotator = (params.get("annotator", [""])[0]).strip().lower()

        # Augment with annotator progress if requested
        if annotator:
            for b in manifest.get("batches", []):
                b_id = b["batch_id"]
                ann_file = ANNOTATIONS_DIR / f"{b_id}_{annotator}.json"
                if ann_file.exists():
                    try:
                        with open(ann_file, "r", encoding="utf-8") as f:
                            saved_labels = json.load(f)
                            labeled_count = sum(1 for v in saved_labels.values() if v.get("gold_decision"))
                            b["labeled_count"] = labeled_count
                    except Exception:
                        b["labeled_count"] = 0
                else:
                    b["labeled_count"] = 0

        self._send_json(manifest)

    def handle_get_batch(self, params):
        batch_id = params.get("id", [""])[0]
        annotator = (params.get("annotator", [""])[0]).strip().lower()

        if not batch_id:
            self._send_json({"error": "Batch id is required"}, status=400)
            return

        batch_file = BATCHES_DIR / f"{batch_id}.json"
        if not batch_file.exists():
            self._send_json({"error": f"Batch file {batch_id}.json not found"}, status=404)
            return

        with open(batch_file, "r", encoding="utf-8") as f:
            cases = json.load(f)

        # Merge with existing annotations for this annotator
        existing_annotations = {}
        if annotator:
            ann_file = ANNOTATIONS_DIR / f"{batch_id}_{annotator}.json"
            if ann_file.exists():
                try:
                    with open(ann_file, "r", encoding="utf-8") as f:
                        existing_annotations = json.load(f)
                except Exception as e:
                    print(f"Error loading annotations for {batch_id}_{annotator}: {e}")

        # Attach existing labels into the case objects for the UI
        for c in cases:
            c_id = c["case_id"]
            if c_id in existing_annotations:
                c["current_label"] = existing_annotations[c_id]
            else:
                c["current_label"] = None

        self._send_json({
            "batch_id": batch_id,
            "annotator": annotator,
            "count": len(cases),
            "cases": cases,
            "annotations": existing_annotations,
        })

    def handle_post_save(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            payload = json.loads(body.decode("utf-8"))

            batch_id = payload.get("batch_id")
            annotator = (payload.get("annotator") or "default").strip().lower()
            case_id = payload.get("case_id")
            label_data = payload.get("label", {})

            if not batch_id or not case_id:
                self._send_json({"error": "batch_id and case_id are required"}, status=400)
                return

            # 1. Update JSON annotations file
            ann_file = ANNOTATIONS_DIR / f"{batch_id}_{annotator}.json"
            annotations = {}
            if ann_file.exists():
                try:
                    with open(ann_file, "r", encoding="utf-8") as f:
                        annotations = json.load(f)
                except Exception:
                    annotations = {}

            # Save or remove if empty
            if label_data.get("gold_decision"):
                annotations[case_id] = label_data
            elif case_id in annotations:
                del annotations[case_id]

            with open(ann_file, "w", encoding="utf-8") as f:
                json.dump(annotations, f, indent=2)

            # 2. Update CSV file for this batch and annotator
            self._update_csv(batch_id, annotator, annotations)

            # 3. Update SQLite database
            try:
                conn = sqlite3.connect(DB_FILE)
                cur = conn.cursor()
                if label_data.get("gold_decision"):
                    cur.execute("""
                        INSERT OR REPLACE INTO annotations (
                            case_id, batch_id, annotator, gold_decision, gold_final_action,
                            gold_missing_evidence, gold_required_authority, gold_clause_ids,
                            user_response_text, user_response_confirmed, notes, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """, (
                        case_id, batch_id, annotator,
                        label_data.get("gold_decision", ""),
                        label_data.get("gold_final_action", ""),
                        label_data.get("gold_missing_evidence", ""),
                        label_data.get("gold_required_authority", ""),
                        label_data.get("gold_clause_ids", ""),
                        label_data.get("user_response_text", ""),
                        str(label_data.get("user_response_confirmed", "")),
                        label_data.get("notes", ""),
                    ))
                else:
                    cur.execute("DELETE FROM annotations WHERE case_id = ?", (case_id,))
                conn.commit()
                conn.close()
            except Exception as dbe:
                print(f"SQLite save warning: {dbe}")

            labeled_count = sum(1 for v in annotations.values() if v.get("gold_decision"))
            self._send_json({
                "status": "success",
                "batch_id": batch_id,
                "case_id": case_id,
                "labeled_count": labeled_count,
            })
        except Exception as e:
            print(f"Error saving annotation: {e}")
            self._send_json({"error": str(e)}, status=500)

    def _update_csv(self, batch_id: str, annotator: str, annotations: dict):
        base_csv = BATCHES_DIR / f"{batch_id}_to_label.csv"
        out_csv = ANNOTATIONS_DIR / f"{batch_id}_{annotator}.csv"

        if not base_csv.exists():
            return

        with open(base_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)

        for row in rows:
            cid = row["case_id"]
            if cid in annotations:
                label = annotations[cid]
                for col in LABEL_COLUMNS:
                    row[col] = label.get(col, "")
            else:
                for col in LABEL_COLUMNS:
                    row[col] = ""

        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def handle_export_csv(self, params):
        batch_id = params.get("batch_id", [""])[0]
        annotator = (params.get("annotator", ["default"])[0]).strip().lower()

        ann_csv = ANNOTATIONS_DIR / f"{batch_id}_{annotator}.csv"
        if not ann_csv.exists():
            base_csv = BATCHES_DIR / f"{batch_id}_to_label.csv"
            if base_csv.exists():
                ann_csv = base_csv
            else:
                self._send_json({"error": "CSV file not found"}, status=404)
                return

        with open(ann_csv, "rb") as f:
            content = f.read()

        filename = f"{batch_id}_{annotator}.csv"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def handle_get_stats(self, params):
        annotator = (params.get("annotator", [""])[0]).strip().lower()
        stats = {
            "annotator": annotator,
            "total_cases": 2000,
            "labeled_total": 0,
            "batch_counts": {},
        }

        if annotator:
            for b_idx in range(1, 21):
                b_id = f"batch_{b_idx:02d}"
                ann_file = ANNOTATIONS_DIR / f"{b_id}_{annotator}.json"
                count = 0
                if ann_file.exists():
                    try:
                        with open(ann_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            count = sum(1 for v in data.values() if v.get("gold_decision"))
                    except Exception:
                        count = 0
                stats["batch_counts"][b_id] = count
                stats["labeled_total"] += count

        self._send_json(stats)


def run_server(port: int = 8080):
    for p in range(port, port + 20):
        try:
            server_address = ("", p)
            httpd = HTTPServer(server_address, LabelingServerHandler)
            print("=" * 65)
            print(f"🚀 SaGate Human Labelling Interface Server running!")
            print(f"👉 Local URL: http://localhost:{p}")
            print(f"👉 Serving from: {APP_DIR}")
            print(f"👉 Data directory: {BATCHES_DIR}")
            print("=" * 65)
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nShutting down server...")
                httpd.server_close()
            return
        except OSError:
            print(f"Port {p} in use, trying port {p + 1}...")

    print("Could not bind to any available port.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SaGate Labelling Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    args = parser.parse_args()
    run_server(args.port)
