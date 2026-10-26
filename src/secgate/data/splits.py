"""Scenario pools and the leakage guard.

The split in data/processed/agentdojo/splits was frozen before any data was generated. Pools:
  train       strict_split == train (includes dev)          — train-source pool
  train_only  train-source minus dev                         — the only pool SFT data may come from
  dev         strict train scenarios whose user task is dev  — B4 threshold / model selection
  test        strict_split == test                           — test-source pool
Scenarios with strict_split == excluded belong to no pool and are never used.
"""

from __future__ import annotations

from typing import Any

from .loaders import AgentDojoData, scenario_id

POOLS = ("train", "train_only", "dev", "test")


class LeakageError(AssertionError):
    pass


class Splits:
    def __init__(self, data: AgentDojoData):
        self._scen = data.scenarios

    def base_pool(self, sid: str) -> str:
        """train | dev | test | excluded."""
        if sid not in self._scen:
            raise KeyError(f"unknown scenario {sid!r}")
        s = self._scen[sid]
        if s["strict_split"] == "train":
            return "dev" if s["user_task_split"] == "dev" else "train"
        return s["strict_split"]

    def in_pool(self, sid: str, pool: str) -> bool:
        if pool not in POOLS:
            raise ValueError(f"unknown pool {pool!r}")
        base = self.base_pool(sid)
        if pool == "train":
            return base in ("train", "dev")
        if pool == "train_only":
            return base == "train"
        return base == pool

    def scenarios_in(self, pool: str) -> list[str]:
        return sorted(sid for sid in self._scen if self.in_pool(sid, pool))

    def assert_pool(self, case: Any, pool: str) -> None:
        """Raise LeakageError unless the case belongs to `pool`.

        Cases built from an AgentDojo scenario are checked through the frozen split; decision-only cases (no
        scenario) carry an explicit `pool` tag set by their author."""
        sid = _scenario_of(case)
        if sid is not None:
            if not self.in_pool(sid, pool):
                raise LeakageError(f"scenario {sid} is in pool {self.base_pool(sid)!r}, not {pool!r}")
            return
        tag = case.get("pool") if isinstance(case, dict) else getattr(case, "pool", None)
        allowed = {"train": {"train", "dev"}, "train_only": {"train"}}.get(pool, {pool})
        if tag not in allowed:
            raise LeakageError(f"case without a scenario has pool tag {tag!r}, not {pool!r}")


def _scenario_of(case: Any) -> str | None:
    if isinstance(case, str):
        return case
    get = case.get if isinstance(case, dict) else (lambda k, d=None: getattr(case, k, d))
    if get("scenario_id"):
        return get("scenario_id")
    if get("suite") and get("user_task_id"):
        return scenario_id(get("suite"), get("user_task_id"), get("injection_task_id"))
    return None
