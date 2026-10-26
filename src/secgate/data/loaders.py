"""Typed access to data/processed/agentdojo (see data/processed/agentdojo/README.md for the schema)."""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .io import read_jsonl

SUITES = ("workspace", "banking")


def scenario_id(suite: str, user_task_id: str, injection_task_id: str | None) -> str:
    return f"{suite}|{user_task_id}|{injection_task_id or 'benign'}"


def message_text(msg: dict) -> str:
    """Plain text of an AgentDojo message (content is a list of {"type": "text", "content": ...} blocks)."""
    content = msg.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, dict):
            parts.append(str(block.get("content") or block.get("text") or ""))
        else:
            parts.append(str(block))
    return "\n".join(p for p in parts if p)


class AgentDojoData:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        if not (self.dir / "scenarios.jsonl").exists():
            raise FileNotFoundError(f"no AgentDojo export under {self.dir}")

    # --- small tables --------------------------------------------------------------------------------
    @cached_property
    def user_tasks(self) -> dict[tuple[str, str], dict]:
        return {(t["suite"], t["id"]): t for t in read_jsonl(self.dir / "user_tasks.jsonl")}

    @cached_property
    def injection_tasks(self) -> dict[tuple[str, str], dict]:
        return {(t["suite"], t["id"]): t for t in read_jsonl(self.dir / "injection_tasks.jsonl")}

    @cached_property
    def tools(self) -> dict[tuple[str, str], dict]:
        return {(t["suite"], t["name"]): t for t in read_jsonl(self.dir / "tools.jsonl")}

    @cached_property
    def injection_vectors(self) -> dict[tuple[str, str], dict]:
        return {(v["suite"], v["vector_id"]): v for v in read_jsonl(self.dir / "injection_vectors.jsonl")}

    @cached_property
    def scenarios(self) -> dict[str, dict]:
        return {s["scenario_id"]: s for s in read_jsonl(self.dir / "scenarios.jsonl")}

    def environment(self, suite: str, kind: str = "default") -> dict:
        with open(self.dir / "environments" / f"{suite}_{kind}.json", encoding="utf-8") as f:
            return json.load(f)

    # --- large tables (streamed) ---------------------------------------------------------------------
    def iter_proposals(self, keep: Callable[[dict], bool] | None = None) -> Iterator[dict]:
        for row in read_jsonl(self.dir / "tool_call_proposals.jsonl.gz"):
            if keep is None or keep(row):
                yield row

    def iter_traces(self, keep: Callable[[dict], bool] | None = None) -> Iterator[dict]:
        for row in read_jsonl(self.dir / "traces.jsonl.gz"):
            if keep is None or keep(row):
                yield row

    def traces_by_id(self, ids: Iterable[str], extra_files: Iterable[str | Path] = ()) -> dict[str, dict]:
        """Load only the traces whose id is in `ids` (from the dataset and any extra trace files)."""
        wanted = set(ids)
        out = {t["trace_id"]: t for t in self.iter_traces(lambda t: t["trace_id"] in wanted)}
        for path in extra_files:
            for t in read_jsonl(path):
                if t["trace_id"] in wanted:
                    out[t["trace_id"]] = t
        return out
