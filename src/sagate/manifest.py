"""manifest.json for every output folder: git commit, config hash, model, seeds, library versions (§9.4)."""

from __future__ import annotations

import json
import platform
import subprocess
import time
from importlib import metadata
from pathlib import Path

from .config import REPO_ROOT, Config
from .gate.cache import content_key

_LIBS = ("torch", "transformers", "peft", "bitsandbytes", "accelerate", "trl", "agentdojo", "numpy")


def git_sha() -> str:
    staged = REPO_ROOT / "GIT_SHA"          # written by kaggle/stage_code.sh (no .git on Kaggle)
    if staged.exists():
        return staged.read_text().strip()
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
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
    m = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_commit": git_sha(),
        "config_hash": content_key(cfg.raw)[:12],
        "config": cfg.raw,
        "seed": cfg.get("seed"),
        "python": platform.python_version(),
        "libraries": lib_versions(),
        **(extra or {}),
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(m, indent=1, default=str))
    return m
