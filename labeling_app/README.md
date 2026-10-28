# Labelling tool

```bash
python labeling_app/server.py      # open http://localhost:8080
```

| File | Role |
|---|---|
| `server.py` | static files + JSON API (`/api/config`, `/api/batches`, `/api/batch`, `/api/vote`, `/api/policies`) |
| `labels.py` | vocabulary, validation, per-annotator vote files (locked, atomic writes), dispute and gold rules |
| `merge.py` | builds `data/synthetic_data/labels/` from all vote files |
| `index.html`, `app.js`, `app.css` | the single labelling page |

Rules the server enforces: an annotator writes only their own file; only in batches assigned to them in
`data/synthetic_data/batches/assignments.json`; a tie-breaker only on disputed cases; primary annotators never
receive another person's votes.

Workflow, assignments and keyboard shortcuts: see the repository [README](../README.md).
