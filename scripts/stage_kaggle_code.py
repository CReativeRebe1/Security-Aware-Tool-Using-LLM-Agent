"""Package the code, configs, policy resources and dataset for Kaggle as a private dataset.

  python scripts/stage_kaggle_code.py --owner <kaggle-username>
  kaggle datasets create  -p build/kaggle-code --dir-mode zip          # first time
  kaggle datasets version -p build/kaggle-code --dir-mode zip -m "<message>"   # every later change

The notebook (notebooks/kaggle_pipeline.ipynb, CODE_SOURCE = "dataset") finds the code by its CODE_VERSION file.
Works on Windows, macOS and Linux (no shell tools needed).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["pyproject.toml", "README.md", "src", "configs", "resources", "annotations", "data/processed"]
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def code_version() -> str:
    def git(*args) -> str:
        try:
            return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                                  timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    sha = git("rev-parse", "--short", "HEAD") or "nogit"
    dirty = git("status", "--porcelain", "--", "src", "configs", "resources", "annotations")
    return sha + ("-dirty" if dirty else "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--owner", required=True, help="Kaggle username that owns the dataset")
    ap.add_argument("--slug", default="secgate-code")
    ap.add_argument("--out", default=str(ROOT / "build" / "kaggle-code"))
    a = ap.parse_args()

    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    dest = out / "secgate"
    dest.mkdir(parents=True)
    for item in INCLUDE:
        src = ROOT / item
        if not src.exists():
            continue
        target = dest / item
        if src.is_dir():
            shutil.copytree(src, target, ignore=SKIP)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    version = code_version()
    (dest / "CODE_VERSION").write_text(version + "\n", encoding="utf-8")
    meta = {"title": a.slug, "id": f"{a.owner}/{a.slug}", "licenses": [{"name": "other"}]}
    (out / "dataset-metadata.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) / 1e6
    print(f"staged code version {version} ({size:.1f} MB) -> {out}")
    print(f"next: kaggle datasets version -p \"{out}\" --dir-mode zip -m \"{version}\"   (or 'create' the first time)")


if __name__ == "__main__":
    main()
