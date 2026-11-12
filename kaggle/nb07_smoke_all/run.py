# NB07 smoke test: every stage (B0 agent, B1-B3 baselines, B4/B5 training, learned-gate evaluation with guards and
# inferred provenance, B4 threshold, report, statistics, end-to-end with the counterfactual probe) on a few cases,
# so a full run never fails hours in. ~45 min on 2 x T4. Output: /kaggle/working/outputs/smoke_summary.json
import glob
import json
import os
import sys
import time

sys.path.insert(0, sorted(glob.glob("/kaggle/input/**/bootstrap.py", recursive=True), key=len)[0].rsplit("/", 1)[0])
import bootstrap  # noqa: E402

OUT = "/kaggle/working/outputs"
N = 4                    # cases per evaluation step
STEPS = 2                # optimizer steps per adapter

root = bootstrap.setup("gpu,train,agentdojo")
py = sys.executable
ann = os.path.join(root, "annotations")
pred = {p: f"{OUT}/predictions/{p}" for p in ("dev", "test")}
results = []


def step(name, cmds):
    """One step; a list of commands runs one per GPU in parallel."""
    t0 = time.time()
    jobs = cmds if isinstance(cmds[0], list) else [cmds]          # always pinned: one job per GPU, own log folder
    codes = bootstrap.run_on_gpus(jobs, os.path.join("/kaggle/working/logs", f"{len(results):02d}"))
    results.append({"step": name, "ok": max(codes) == 0, "minutes": round((time.time() - t0) / 60, 1)})
    print(f"=== {name}: {'OK' if max(codes) == 0 else 'FAILED'} ({results[-1]['minutes']} min)", flush=True)


def gate(cond, pool, *extra):
    return [py, "-m", "sagate.eval.run_gate", "--condition", cond, "--cases", f"{ann}/{pool}_cases.jsonl",
            "--pool", pool, "--limit", str(N), "--out", pred[pool], *extra]


ad = ["--adapter-dir", f"{OUT}/adapters"]
step("B0 agent, 1 scenario", [py, "-m", "sagate.agent.run_b0", "--out", f"{OUT}/b0", "--pools", "test", "--limit", "1"])
step("B1 rules", gate("b1_rules", "test"))
step("B2 / B3 prompted", [gate("b2_prompt_binary", "test"), gate("b3_prompt_4way", "test")])
step("training data", [py, "-c", ";".join([
    "import subprocess,sys",
    f"subprocess.run([sys.executable,'-m','sagate.train.variants','--pool','train_only','--n','20','--out','{OUT}/sft/v.jsonl'],check=True)",
    f"subprocess.run([sys.executable,'-m','sagate.train.build_sft','--condition','b5_qlora_4way','b4_qlora_binary','--cases','{OUT}/sft/v.jsonl','{ann}/train_human.jsonl','--out','{OUT}/sft'],check=True)"])])
# train on the LONGEST examples, so a memory problem shows here and not hours into the real run
step("longest examples", [py, "-c", ";".join([
    "import json",
    *[f"r=[json.loads(l) for l in open('{OUT}/sft/{c}.jsonl')];r.sort(key=lambda x:-len(json.dumps(x['messages'])));"
      f"open('{OUT}/sft/{c}_long.jsonl','w').writelines(json.dumps(x)+chr(10) for x in r[:16*{STEPS}])"
      for c in ("b5_qlora_4way", "b4_qlora_binary")]])])
step("B5 / B4 training (longest examples)", [[py, "-m", "sagate.train.train_qlora", "--condition", c, "--sft",
                                              f"{OUT}/sft/{c}_long.jsonl", "--out", OUT, "--max-steps", str(STEPS)]
                                             for c in ("b5_qlora_4way", "b4_qlora_binary")])
step("B5 / B4 on dev", [gate("b5_qlora_4way", "dev", *ad), gate("b4_qlora_binary", "dev", *ad)])
step("B5 test: clean, noisy, guarded, inferred", [
    [py, "-c", ";".join(["import subprocess,sys"] + [f"subprocess.run({c!r},check=True)" for c in (
        gate("b5_qlora_4way", "test", *ad, "--cite"), gate("b5_qlora_4way", "test", *ad, "--responses", "noisy"),
        gate("b5_guarded", "test", *ad))])],
    [py, "-c", ";".join(["import subprocess,sys"] + [f"subprocess.run({c!r},check=True)" for c in (
        gate("b4_qlora_binary", "test", *ad), gate("b5_inferred_prov", "test", *ad))])]])
step("B4 threshold (dev) and matched test", [py, "-c", ";".join([
    "import subprocess,sys",
    f"subprocess.run([sys.executable,'-m','sagate.eval.pareto','select','--b4','{pred['dev']}/b4_qlora_binary.jsonl','--b5','{pred['dev']}/b5_qlora_4way.jsonl','--cases','{ann}/dev_cases.jsonl','--out','{pred['dev']}/b4_threshold.json'],check=True)",
    f"subprocess.run([sys.executable,'-m','sagate.eval.pareto','apply','--pred','{pred['test']}/b4_qlora_binary.jsonl','--threshold-file','{pred['dev']}/b4_threshold.json','--out','{pred['test']}/b4_qlora_binary_matched.jsonl'],check=True)"])])
step("report", [py, "-c", ";".join([
    "import subprocess,sys,glob",
    f"subprocess.run([sys.executable,'-m','sagate.eval.report','--cases','{ann}/test_cases.jsonl','--pred',*sorted(glob.glob('{pred['test']}/*.jsonl')),'--json','{pred['test']}/report.json'],check=True)"])])
step("statistics (NB06 path)", [py, "-c", ";".join([
    "import subprocess,sys,glob",
    "subprocess.run([sys.executable,'-m','pip','install','-q','matplotlib'],check=True)",
    f"subprocess.run([sys.executable,'-m','sagate.eval.analysis','--cases','{ann}/test_cases.jsonl','--pred',*sorted(glob.glob('{pred['test']}/*.jsonl')),'--out','{OUT}/report'],check=True)"])])
step("end-to-end B5 + counterfactual, banking scenarios (payments reach the gate)",
     [py, "-m", "sagate.agent.run_e2e", "--condition", "b5_counterfactual", "--out", f"{OUT}/e2e", *ad,
      "--suites", "banking", "--limit", "3"])

json.dump(results, open(f"{OUT}/smoke_summary.json", "w"), indent=1)
print(json.dumps(results, indent=1))
sys.exit(0 if all(r["ok"] for r in results) else 1)
