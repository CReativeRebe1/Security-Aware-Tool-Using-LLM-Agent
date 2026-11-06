# Review tool

```bash
python labeling_app/server.py      # open http://localhost:8080
```

| File | Role |
|---|---|
| `server.py` | static files + JSON API (`/api/config`, `/api/batches`, `/api/batch`, `/api/suggestions`, `/api/vote`, `/api/policies`) |
| `labels.py` | vocabulary, validation, per-reviewer review files (locked, atomic writes), the two-reviewer rules |
| `merge.py` | builds `data/synthetic_data/labels/` from all review files |
| `index.html`, `app.js`, `app.css` | the review page |

Rules the server enforces: every batch in `data/synthetic_data/batches/assignments.json` has exactly two
reviewers; only those two can open the batch, get its suggestions or write reviews for it; each writes only their
own file; nobody ever receives another person's reviews.

Workflow, assignments and keyboard shortcuts: see the repository [README](../README.md).
