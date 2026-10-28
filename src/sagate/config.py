"""Config loading: configs/base.yaml + (on Kaggle) configs/kaggle.yaml + optional condition file.

Relative paths resolve against the repository root, so the same config works locally and on Kaggle
(where the code is unpacked to /kaggle/tmp/sagate-code).
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FOUR_WAY = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")


def on_kaggle() -> bool:
    return "KAGGLE_KERNEL_RUN_TYPE" in os.environ


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_yaml(path: str | Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


@dataclass
class Config:
    raw: dict
    root: Path = REPO_ROOT

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def path(self, key: str) -> Path | None:
        """Resolve paths.<key> against the repo root (absolute paths are kept)."""
        value = self.raw["paths"].get(key)
        if value is None:
            return None
        p = Path(value)
        return p if p.is_absolute() else self.root / p

    @property
    def data_dir(self) -> Path:
        return self.path("data_dir")

    @property
    def resources_dir(self) -> Path:
        return self.path("resources_dir")

    @property
    def outputs_dir(self) -> Path:
        return self.path("outputs_dir")


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Config:
    """Load base.yaml, then kaggle.yaml when on Kaggle, then `path` (if it is not base.yaml), then overrides."""
    raw = _read_yaml(REPO_ROOT / "configs" / "base.yaml")
    if on_kaggle():
        raw = _merge(raw, _read_yaml(REPO_ROOT / "configs" / "kaggle.yaml"))
    if path is not None and Path(path).resolve() != (REPO_ROOT / "configs" / "base.yaml").resolve():
        raw = _merge(raw, _read_yaml(path))
    if overrides:
        raw = _merge(raw, overrides)
    return Config(raw=raw)


@dataclass
class Condition:
    """One experimental condition (configs/conditions/*.yaml). Read by the evaluator and the SFT builder."""

    name: str
    gate_kind: str                       # rules | llm
    adapter: str | None
    decision_space: tuple[str, ...]
    provenance: str                      # oracle | inferred | none
    authority: bool = True
    sensitivity: bool = True
    rag: bool = True
    intermediate: bool = True
    resolution: bool = True
    extra: dict = field(default_factory=dict)

    @property
    def binary(self) -> bool:
        return set(self.decision_space) == {"ALLOW", "BLOCK"}

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        ev = d.get("evidence", {})
        rag = ev.get("rag", True)
        if isinstance(rag, dict):
            rag = rag.get("enabled", True)
        space = tuple(d.get("decision_space", FOUR_WAY))
        bad = set(space) - set(FOUR_WAY)
        if bad or "ALLOW" not in space or "BLOCK" not in space:
            raise ValueError(f"invalid decision_space {space}")
        known = {"name", "gate", "decision_space", "evidence", "supervision", "resolution"}
        return cls(
            name=d["name"],
            gate_kind=d["gate"]["kind"],
            adapter=d["gate"].get("adapter"),
            decision_space=space,
            provenance=str(ev.get("provenance", "oracle")),
            authority=bool(ev.get("authority", True)),
            sensitivity=bool(ev.get("sensitivity", True)),
            rag=bool(rag),
            intermediate=bool(d.get("supervision", {}).get("intermediate", True)),
            resolution=bool(d.get("resolution", {}).get("enabled", True)),
            extra={k: v for k, v in d.items() if k not in known},
        )


def load_condition(name_or_path: str | Path) -> Condition:
    p = Path(name_or_path)
    if not p.suffix:
        p = REPO_ROOT / "configs" / "conditions" / f"{name_or_path}.yaml"
    return Condition.from_dict(_read_yaml(p))
