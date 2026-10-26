"""Configuration: configs/base.yaml, then configs/kaggle.yaml on Kaggle, then an optional override file.

Relative paths resolve against the repository root, so the same files work locally and on Kaggle.
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
    return "KAGGLE_KERNEL_RUN_TYPE" in os.environ or Path("/kaggle/working").is_dir()


def read_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@dataclass
class Config:
    raw: dict
    root: Path = REPO_ROOT

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def path(self, key: str) -> Path | None:
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
    raw = read_yaml(REPO_ROOT / "configs" / "base.yaml")
    if on_kaggle():
        raw = deep_merge(raw, read_yaml(REPO_ROOT / "configs" / "kaggle.yaml"))
    if path is not None:
        raw = deep_merge(raw, read_yaml(path))
    if overrides:
        raw = deep_merge(raw, overrides)
    return Config(raw)


@dataclass(frozen=True)
class Condition:
    """One experimental condition (configs/conditions/<name>.yaml), shared by the evaluator and the trainer."""

    name: str
    gate_kind: str                          # rules | llm
    decision_space: tuple[str, ...]
    adapter: str | None = None
    provenance: str = "oracle"              # oracle | inferred | none
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
        space = tuple(d.get("decision_space", FOUR_WAY))
        if not {"ALLOW", "BLOCK"} <= set(space) or set(space) - set(FOUR_WAY):
            raise ValueError(f"{d.get('name')}: invalid decision_space {space}")
        ev = d.get("evidence", {})
        known = {"name", "gate", "decision_space", "evidence", "supervision", "resolution"}
        return cls(
            name=d["name"],
            gate_kind=d["gate"]["kind"],
            decision_space=space,
            adapter=d["gate"].get("adapter"),
            provenance=str(ev.get("provenance", "oracle")),
            authority=bool(ev.get("authority", True)),
            sensitivity=bool(ev.get("sensitivity", True)),
            rag=bool(ev.get("rag", True)),
            intermediate=bool(d.get("supervision", {}).get("intermediate", True)),
            resolution=bool(d.get("resolution", {}).get("enabled", True)),
            extra={k: v for k, v in d.items() if k not in known},
        )


def load_condition(name_or_path: str | Path) -> Condition:
    p = Path(name_or_path)
    if p.suffix not in (".yaml", ".yml"):
        p = REPO_ROOT / "configs" / "conditions" / f"{name_or_path}.yaml"
    return Condition.from_dict(read_yaml(p))
