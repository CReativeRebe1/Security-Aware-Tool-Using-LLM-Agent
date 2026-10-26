"""Append-only JSONL stores keyed by a content hash, so GPU jobs can die and resume (P6, §9.4)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator


def content_key(*parts: Any) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str).encode())
        h.update(b"\x00")
    return h.hexdigest()


class JsonlStore:
    """{"key": ..., **record} lines; `flush()` after each write; existing keys are loaded on open."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rows: dict[str, dict] = {}
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:   # a session killed mid-write leaves a partial last line
                        continue
                    self._rows[r["key"]] = r
        self._fh = open(self.path, "a", encoding="utf-8")

    def __contains__(self, key: str) -> bool:
        return key in self._rows

    def __len__(self) -> int:
        return len(self._rows)

    def get(self, key: str) -> dict | None:
        return self._rows.get(key)

    def put(self, key: str, record: dict) -> None:
        row = {"key": key, **record}
        self._rows[key] = row
        self._fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def values(self) -> Iterator[dict]:
        return iter(self._rows.values())

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "JsonlStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class GateCache:
    """hash(model, adapter, decision space, prompt) -> GateOutput dict."""

    def __init__(self, path: str | Path | None):
        self.store = JsonlStore(path) if path else None

    def key(self, model_id: str, adapter: str | None, space: tuple, intermediate: bool, messages: list,
            threshold: float | None = None) -> str:
        return content_key(model_id, adapter, list(space), intermediate, messages, threshold)

    def get(self, key: str) -> dict | None:
        if self.store is None:
            return None
        r = self.store.get(key)
        return r["output"] if r else None

    def put(self, key: str, output: dict) -> None:
        if self.store is not None:
            self.store.put(key, {"output": output})
