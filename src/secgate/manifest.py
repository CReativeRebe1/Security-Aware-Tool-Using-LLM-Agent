"""manifest.json next to every output: code version, config hash, seed and library versions."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from importlib import metadata
from pathlib import Path

from .config import REPO_ROOT, Config

_LIBS = ("torch", "transformers", "peft", "bitsandbytes", "accelerate", "agentdojo", "numpy")


def code_version() -> str:
    """CODE_VERSION file written by scripts/stage_kaggle_code.py, else the git commit."""
    stamp = REPO_ROOT / "CODE_VERSION"
    if stamp.exists():
        return stamp.read_text().strip()
    try:
        sha = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        return sha or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def lib_versions() -> dict:
    out = {}
    for lib in _LIBS:
        try:
            out[lib] = metadata.version(lib)
        except metadata.PackageNotFoundError:
            pass
    return out


def write_manifest(path: str | Path, cfg: Config, extra: dict | None = None) -> dict:
    blob = json.dumps(cfg.raw, sort_keys=True, default=str)
    man = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "code_version": code_version(),
        "config_sha1": hashlib.sha1(blob.encode()).hexdigest()[:12],
        "seed": cfg.get("seed"),
        "python": platform.python_version(),
        "libraries": lib_versions(),
        **(extra or {}),
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(man, indent=1, default=str), encoding="utf-8")
    return man
