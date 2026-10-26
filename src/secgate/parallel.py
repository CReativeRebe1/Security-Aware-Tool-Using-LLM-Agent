"""Run independent jobs one per GPU (Kaggle T4 x2): each job is a subprocess with CUDA_VISIBLE_DEVICES set, its
output streamed to a log file. One 8B nf4 model (~6 GB) fits per T4, so two jobs run side by side."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path


def gpu_count() -> int:
    try:
        out = subprocess.check_output(["nvidia-smi", "-L"], text=True, stderr=subprocess.DEVNULL)
        return len([l for l in out.splitlines() if l.strip()])
    except (OSError, subprocess.CalledProcessError):
        return 0


def run_jobs(jobs: list[list[str]], log_dir: str | Path, tail: int = 20, poll_s: float = 15.0) -> list[int]:
    """jobs[i] runs on GPU i % n_gpu; at most n_gpu jobs at a time. Returns exit codes in job order."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    n = max(gpu_count(), 1)
    codes: dict[int, int] = {}
    pending = list(enumerate(jobs))
    running: dict[int, tuple] = {}
    while pending or running:
        free = [g for g in range(n) if g not in {v[2] for v in running.values()}]
        while pending and free:
            i, cmd = pending.pop(0)
            g = free.pop(0)
            env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(g), PYTHONUNBUFFERED="1")
            fh = open(log_dir / f"job{i}.log", "w", encoding="utf-8")
            print(f"[gpu {g}] job{i}: {' '.join(cmd)}", flush=True)
            running[i] = (subprocess.Popen(cmd, env=env, stdout=fh, stderr=subprocess.STDOUT), fh, g)
        for i, (proc, fh, g) in list(running.items()):
            if proc.poll() is None:
                continue
            fh.close()
            codes[i] = proc.returncode
            del running[i]
            lines = (log_dir / f"job{i}.log").read_text(encoding="utf-8", errors="replace").splitlines()
            print(f"job{i} (gpu {g}) exited {proc.returncode}; last lines:", *lines[-tail:], sep="\n  ", flush=True)
        if running:
            time.sleep(poll_s)
    return [codes[i] for i in range(len(jobs))]
