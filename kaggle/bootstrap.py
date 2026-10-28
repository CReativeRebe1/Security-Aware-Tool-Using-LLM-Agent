"""Kaggle bootstrap, shipped next to the code tarball in the `sagate-code` dataset.

setup(): finds the staged code under /kaggle/input, unpacks it to /kaggle/tmp/sagate-code (not persisted, does
not count against /kaggle/working), pip-installs it and prints the staged git SHA first so a stale dataset
version is visible in the log. run_on_gpus(): one subprocess per GPU with CUDA_VISIBLE_DEVICES (§9.1).
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

WORK = "/kaggle/working"


def _tmp_root() -> str:
    for d in ("/kaggle/tmp", "/tmp"):
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except OSError:
            continue
    raise RuntimeError("no writable tmp dir")


def find_staged() -> str:
    hits = sorted(glob.glob("/kaggle/input/**/GIT_SHA", recursive=True), key=len)
    if not hits:
        raise FileNotFoundError("sagate-code dataset not attached (no GIT_SHA under /kaggle/input)")
    return os.path.dirname(hits[0])


def setup(extras: str = "gpu,agentdojo") -> str:
    src = find_staged()
    sha = open(os.path.join(src, "GIT_SHA")).read().strip()
    print(f"sagate code version: {sha}  (from {src})", flush=True)
    dest = os.path.join(_tmp_root(), "sagate-code")
    marker = os.path.join(dest, "GIT_SHA")
    if not (os.path.exists(marker) and open(marker).read().strip() == sha):
        shutil.rmtree(dest, ignore_errors=True)
        tgz = os.path.join(src, "sagate-code.tar.gz")
        if os.path.exists(tgz):
            with tarfile.open(tgz) as t:
                t.extractall(dest)
        else:   # Kaggle may have auto-extracted the archive
            root = os.path.dirname(sorted(glob.glob(os.path.join(src, "**", "pyproject.toml"), recursive=True),
                                          key=len)[0])
            shutil.copytree(root, dest)
        with open(marker, "w") as f:
            f.write(sha)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", f"{dest}[{extras}]"], check=True)
    sys.path.insert(0, os.path.join(dest, "src"))
    os.environ.setdefault("HF_HOME", os.path.join(_tmp_root(), "hf"))
    subprocess.run(["nvidia-smi", "-L"], check=False)
    return dest


def collect_adapters(dest: str = os.path.join(WORK, "adapters")) -> str | None:
    """One adapter dir for --adapter-dir out of every attached NB03 output (training may be split over several
    kernels): adapters/<condition> is linked from the most recently trained copy (manifest "created")."""
    best = {}
    for cfg in glob.glob("/kaggle/input/**/adapters/*/adapter_config.json", recursive=True):
        d = os.path.dirname(cfg)
        try:
            created = json.load(open(os.path.join(d, "manifest.json")))["created"]
        except (OSError, ValueError, KeyError):
            created = ""
        name = os.path.basename(d)
        if name not in best or created > best[name][0]:
            best[name] = (created, d)
    if not best:
        return None
    os.makedirs(dest, exist_ok=True)
    for name, (created, d) in sorted(best.items()):
        link = os.path.join(dest, name)
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(d, link)
        print(f"adapter {name}: {d} (trained {created or '?'})", flush=True)
    return dest


def run(cmd: list, log: str | None = None) -> int:
    print("$", " ".join(cmd), flush=True)
    if log is None:
        return subprocess.run(cmd).returncode
    with open(log, "w") as f:
        return subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode


def run_on_gpus(jobs: list, log_dir: str = os.path.join(WORK, "logs")) -> list:
    """jobs: list of argv lists; job i runs on GPU i (wraps around). Logs stream to log_dir/job<i>.log."""
    os.makedirs(log_dir, exist_ok=True)
    try:
        n_gpu = len(subprocess.check_output(["nvidia-smi", "-L"], text=True).strip().splitlines())
    except (OSError, subprocess.CalledProcessError):
        n_gpu = 1
    procs = []
    for i, cmd in enumerate(jobs):
        env = dict(os.environ, CUDA_VISIBLE_DEVICES=str(i % max(n_gpu, 1)), PYTHONUNBUFFERED="1",
                   PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")   # fragmentation caused NB01 OOMs
        log = open(os.path.join(log_dir, f"job{i}.log"), "w")
        print(f"[gpu {i % max(n_gpu, 1)}] $ {' '.join(cmd)}", flush=True)
        procs.append((subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT), log, i))
    codes = []
    while procs:
        for p in list(procs):
            proc, log, i = p
            if proc.poll() is not None:
                log.close()
                print(f"job{i} exited with {proc.returncode}; tail of log:", flush=True)
                with open(log.name) as f:
                    print("".join(f.readlines()[-15:]), flush=True)
                codes.append(proc.returncode)
                procs.remove(p)
        time.sleep(20)
    return codes
