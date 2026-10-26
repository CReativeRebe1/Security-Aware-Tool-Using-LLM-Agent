"""Typed readers for every file in data/processed/agentdojo (schema: data/processed/agentdojo/README.md)."""

from __future__ import annotations

import gzip
import json
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Iterator


def read_jsonl(path: str | Path) -> Iterator[dict]:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: str | Path, rows: Iterable[dict]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def scenario_id(suite: str, user_task_id: str, injection_task_id: str | None) -> str:
    return f"{suite}|{user_task_id}|{injection_task_id or 'benign'}"


class AgentDojoData:
    """Lazy access to the processed AgentDojo export. Small files are cached; traces/proposals stream."""

    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)

    # --- small tables -------------------------------------------------------------------------------
    @cached_property
    def user_tasks(self) -> dict[tuple[str, str], dict]:
        return {(t["suite"], t["id"]): t for t in read_jsonl(self.dir / "user_tasks.jsonl")}

    @cached_property
    def injection_tasks(self) -> dict[tuple[str, str], dict]:
        return {(t["suite"], t["id"]): t for t in read_jsonl(self.dir / "injection_tasks.jsonl")}

    @cached_property
    def injection_vectors(self) -> dict[tuple[str, str], dict]:
        return {(v["suite"], v["vector_id"]): v for v in read_jsonl(self.dir / "injection_vectors.jsonl")}

    @cached_property
    def tools(self) -> dict[tuple[str, str], dict]:
        return {(t["suite"], t["name"]): t for t in read_jsonl(self.dir / "tools.jsonl")}

    @cached_property
    def scenarios(self) -> dict[str, dict]:
        return {s["scenario_id"]: s for s in read_jsonl(self.dir / "scenarios.jsonl")}

    @cached_property
    def split(self) -> dict:
        with open(self.dir / "splits" / "scenario_split.json") as f:
            return json.load(f)

    def environment(self, suite: str, kind: str = "default") -> dict:
        with open(self.dir / "environments" / f"{suite}_{kind}.json") as f:
            return json.load(f)

    def user_prompt(self, suite: str, user_task_id: str) -> str | None:
        t = self.user_tasks.get((suite, user_task_id))
        return t.get("prompt") if t else None

    # --- large tables (streamed) ----------------------------------------------------------------------
    def iter_proposals(self, where: Callable[[dict], bool] | None = None) -> Iterator[dict]:
        for r in read_jsonl(self.dir / "tool_call_proposals.jsonl.gz"):
            if where is None or where(r):
                yield r

    def iter_traces(self, where: Callable[[dict], bool] | None = None) -> Iterator[dict]:
        for r in read_jsonl(self.dir / "traces.jsonl.gz"):
            if where is None or where(r):
                yield r

    def traces_by_id(self, trace_ids: Iterable[str], extra_files: Iterable[str | Path] = ()) -> dict[str, dict]:
        """Load only the requested traces (the full file holds ~23k traces with messages)."""
        wanted = set(trace_ids)
        out: dict[str, dict] = {}
        for src in [self.dir / "traces.jsonl.gz", *map(Path, extra_files)]:
            for r in read_jsonl(src):
                if r["trace_id"] in wanted:
                    out[r["trace_id"]] = r
        return out


def message_text(message: dict) -> str:
    """Plain text of an AgentDojo message (content is a list of {type, content} blocks, or a string)."""
    content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type", "text") == "text":
                parts.append(str(block.get("content", "")))
        else:
            parts.append(str(block))
    return "\n".join(parts)
