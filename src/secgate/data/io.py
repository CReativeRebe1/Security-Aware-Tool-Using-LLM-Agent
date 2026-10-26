"""JSONL helpers (plain or gzip) and an append-only keyed store that makes long jobs resumable."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator


def _open(path: str | Path, mode: str):
    if str(path).endswith(".gz"):
        return gzip.open(path, mode + "t", encoding="utf-8")
    return open(path, mode, encoding="utf-8")


def read_jsonl(path: str | Path) -> Iterator[dict]:
    with _open(path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with _open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
            n += 1
    return n


def content_key(*parts: Any) -> str:
    """Stable hash of JSON-serialisable parts."""
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


class KeyedStore:
    """Append-only JSONL of {"key", "value"} rows. Re-opening loads the keys already written, so a job that dies
    can be restarted and skips finished work. Every put is flushed immediately."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.items: dict[str, Any] = {}
        self._fh = None
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:      # torn last line from a killed job
                        continue
                    self.items[row["key"]] = row["value"]

    def __contains__(self, key: str) -> bool:
        return key in self.items

    def __len__(self) -> int:
        return len(self.items)

    def get(self, key: str, default: Any = None) -> Any:
        return self.items.get(key, default)

    def values(self) -> list:
        return list(self.items.values())

    def put(self, key: str, value: Any) -> None:
        self.items[key] = value
        if self.path is None:
            return
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="utf-8")
        self._fh.write(json.dumps({"key": key, "value": value}, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "KeyedStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
