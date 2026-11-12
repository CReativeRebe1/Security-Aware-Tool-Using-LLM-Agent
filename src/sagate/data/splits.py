"""Scenario split lookup and the leakage guard (ARCHITECTURE.md P5, §10).

Pools: "train" = strict_split train (includes dev), "train_only" = train without dev (use for SFT data, so the
B4 threshold is never selected on seen scenarios), "dev" = strict train with user_task_split dev,
"test" = strict_split test. "excluded" scenarios are never used.
"""

from __future__ import annotations

from typing import Any

from .loaders import AgentDojoData, scenario_id


class LeakageError(AssertionError):
    pass


class Splits:
    def __init__(self, data: AgentDojoData):
        self._scen = data.scenarios

    def scenario(self, sid: str) -> dict:
        if sid not in self._scen:
            raise KeyError(f"unknown scenario {sid!r}")
        return self._scen[sid]

    def pool_of(self, sid: str) -> str:
        """train | dev | test | excluded. Dev is a subset of the train-source pool."""
        s = self.scenario(sid)
        if s["strict_split"] == "train":
            return "dev" if s["user_task_split"] == "dev" else "train"
        return s["strict_split"]

    def in_pool(self, sid: str, pool: str) -> bool:
        p = self.pool_of(sid)
        if pool == "train":
            return p in ("train", "dev")
        if pool == "train_only":      # SFT data: train-source minus the dev pool used for threshold selection
            return p == "train"
        return p == pool

    def scenarios_in(self, pool: str) -> list[str]:
        return [sid for sid in self._scen if self.in_pool(sid, pool)]

    def assert_pool(self, case: Any, pool: str) -> None:
        """Raise LeakageError unless the case's scenario belongs to `pool` (train allows dev)."""
        sid = _case_scenario(case)
        if sid is None:
            # decision-only NL cases carry an explicit pool tag instead of a scenario
            tag = case.get("pool") if isinstance(case, dict) else getattr(case, "pool", None)
            ok = tag == pool or (pool == "train" and tag == "dev") or (pool == "train_only" and tag == "train")
            if not ok:
                raise LeakageError(f"case without scenario has pool {tag!r}, expected {pool!r}")
            return
        if not self.in_pool(sid, pool):
            raise LeakageError(f"scenario {sid} is in pool {self.pool_of(sid)!r}, expected {pool!r}")


def _case_scenario(case: Any) -> str | None:
    if isinstance(case, str):
        return case
    get = case.get if isinstance(case, dict) else (lambda k, d=None: getattr(case, k, d))
    sid = get("scenario_id")
    if sid:
        return sid
    if get("suite") and get("user_task_id"):
        return scenario_id(get("suite"), get("user_task_id"), get("injection_task_id"))
    return None
