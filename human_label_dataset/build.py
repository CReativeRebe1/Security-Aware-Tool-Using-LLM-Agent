#!/usr/bin/env python3
"""Build the final human-label dataset from the committed reviews of the labeling branch.

    python human_label_dataset/build.py

Inputs : data/synthetic_data/batches/annotations/<reviewer>/<batch>.json   (the reviews)
         data/synthetic_data/batches/suggestions.json                      (suggested labels, for explanations)
         human_label_dataset/decisions.json                                (team calls on disputes and comments)
Outputs: human_label_dataset/final/human_labels.jsonl   every reviewed case with a final label, a tier and its input
                                                         (person names varied per case, see names.py)
         human_label_dataset/final/pending.jsonl        reviewed cases still waiting for a call in decisions.json
         human_label_dataset/final/summary.json         counts, label mix, reviewer statistics, agreement
         human_label_dataset/REPORT.md                  the same, readable
         human_label_dataset/DECISIONS.md               the open calls with both labels and the recommendation

Tiers (how much human checking a label had):
  A  two careful reviews that agree
  B  one careful review (the other reviewer is missing, or saved it in under 3 seconds)
  C  only fast reviews (every review saved under 3 seconds after the previous one: effectively unchecked)
  T  decided by the team in decisions.json
A review counts as "fast" when it was saved less than FAST_SECONDS after the same reviewer's previous save in
that batch; that is too quick to read a case.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "labeling_app"))
import labels as L  # noqa: E402
from merge import cohen_kappa, krippendorff_alpha  # noqa: E402

sys.path.insert(0, str(HERE))
import names  # noqa: E402

FAST_SECONDS = 3
# Reviewers whose fast saves still count as careful: they labelled these cases with the earlier schema and only
# re-marked the same labels in the review tool, so the save times do not show their reading time.
EARLIER_SCHEMA_REVIEWERS = {"prabhash"}
FIELDS = ("decision", "final_action", "missing_evidence", "required_authority")
OUT = HERE / "final"


def fast_votes(votes: dict) -> set:
    """case ids whose save came less than FAST_SECONDS after the previous save of the same file."""
    order = sorted(votes.values(), key=lambda v: v["updated_at"])
    out = set()
    for prev, cur in zip(order, order[1:]):
        gap = (datetime.fromisoformat(cur["updated_at"]) - datetime.fromisoformat(prev["updated_at"])).total_seconds()
        if gap < FAST_SECONDS:
            out.add(cur["case_id"])
    return out


def fields_of(v: dict) -> dict:
    return {f: v.get("gold_" + f) for f in FIELDS}


def with_noisy(ur: dict | None, sug: dict) -> dict | None:
    """Keep the noisy reply variant from the suggestion when the clean reply is the suggested one."""
    s = sug.get("user_response")
    if not ur:
        return None
    if s and ur.get("text") == s.get("text"):
        return {**s, **{k: ur[k] for k in ("text", "confirmed") if k in ur}}
    return ur


def main() -> None:
    asg = L.load_assignments()
    sug_all = L.load_suggestions()
    decisions = json.loads((HERE / "decisions.json").read_text(encoding="utf-8"))["items"]

    # explanation texts that the suggestions reuse for different decisions (written per family, not per case)
    dec_by_text = defaultdict(set)
    for s in sug_all.values():
        dec_by_text[s["explanation"]].add(s["decision"])
    template_texts = {t for t, d in dec_by_text.items() if len(d) > 1}

    final, pending = [], []
    reviewer_stats = defaultdict(lambda: Counter())
    pair_units, pair_kappa = [], defaultdict(lambda: ([], []))
    seen_decisions = set()

    for bid, b in sorted(asg["batches"].items()):
        votes = {r: L.read_votes(r, bid) for r in b["reviewers"]}
        fast = {r: fast_votes(v) for r, v in votes.items()}
        for r, v in votes.items():
            for cid, x in v.items():
                st = reviewer_stats[r]
                st["reviews"] += 1
                st[x["review"]["status"]] += 1
                st["fast"] += cid in fast[r]
                st["same_as_suggestion"] += (not L.cannot_label(x)) and fields_of(x) == {f: sug_all[cid][f] for f in FIELDS}
        for pos, case in enumerate(L.load_batch(bid), 1):
            cid = case["case_id"]
            sug = sug_all[cid]
            revs = {r: votes[r][cid] for r in b["reviewers"] if cid in votes[r]}
            if not revs:
                continue
            careful = {r for r in revs if cid not in fast[r] or r in EARLIER_SCHEMA_REVIEWERS}
            meta = case["raw_case"]["meta"]
            base = {"case_id": cid, "batch_id": bid, "position": pos, "phase": b["phase"], "suite": case["suite"],
                    "category": case["category"], "difficulty": case["difficulty"], "round": case["round"],
                    "family": meta.get("family"), "variant": meta.get("variant"),
                    "reviews": {r: {"status": v["review"]["status"], "fast": r not in careful,
                                    **({"reason": v["review"].get("reason"), "note": v["review"].get("note")}
                                       if L.cannot_label(v) else fields_of(v))} for r, v in revs.items()}}
            comments = {r: (v["review"].get("explanation") or v["review"].get("note") or "").strip()
                        for r, v in revs.items() if v["review"]["status"] != "accepted"}
            comments = {r: t for r, t in comments.items() if t and t != sug["explanation"].strip()}
            if comments:
                base["reviewer_comments"] = comments

            a, c = (list(revs.values()) + [None])[:2]
            status, gold = L.resolve(a, c)
            if len(revs) == 2 and L.is_complete(a) and L.is_complete(c):
                pair_units.append([a["gold_decision"], c["gold_decision"]])
                xs, ys = pair_kappa[tuple(revs)]
                xs.append(a["gold_decision"])
                ys.append(c["gold_decision"])

            if cid in decisions:
                seen_decisions.add(cid)
                d = decisions[cid]
                choice = d.get("choice")
                if choice is None:
                    pending.append({**base, "why": d["flag"], "recommended": d["recommended"]})
                    continue
                if choice == "drop":
                    continue
                if choice == "recommended":
                    rec = d["recommended"]
                    lab = {f: rec[f] for f in FIELDS}
                    clauses, expl = rec["clause_ids"], rec["explanation"]
                    ur = sug.get("user_response") if rec.get("user_response") == "suggestion" else rec.get("user_response")
                elif choice == "suggestion":
                    lab = {f: sug[f] for f in FIELDS}
                    clauses, expl, ur = sug["clause_ids"], sug["explanation"], sug.get("user_response")
                elif choice in revs and not L.cannot_label(revs[choice]):
                    v = revs[choice]
                    lab, clauses = fields_of(v), v.get("gold_clause_ids") or []
                    expl = v["review"].get("explanation") or sug["explanation"]
                    ur = with_noisy(v.get("user_response"), sug)
                else:
                    raise SystemExit(f"{cid}: choice {choice!r} is not usable")
                tier = "T"
            else:
                if status == "agreed":
                    v = a
                elif status == "partial" and len(revs) == 1 and L.is_complete(a):
                    v = a
                else:
                    pending.append({**base, "why": f"{status} and not in decisions.json"})
                    continue
                lab = fields_of(v)
                clauses = sorted({x for r in revs.values() for x in (r.get("gold_clause_ids") or [])})
                ur = with_noisy(v.get("user_response"), sug)
                expl = sug["explanation"] if lab == {f: sug[f] for f in FIELDS} else (v["review"].get("explanation") or "")
                agreeing = [r for r in careful if L.is_complete(revs[r]) and fields_of(revs[r])["decision"] == lab["decision"]]
                tier = "A" if len(agreeing) >= 2 else "B" if agreeing else "C"
            if lab["decision"] != "ASK_USER" and not (ur and ur.get("text")):
                ur = None
            inp = case["raw_case"]["input"]
            nmap = names.make_map(cid, names.strings([inp, ur, expl]))
            final.append({**base, **{"gold_" + f: lab[f] for f in FIELDS}, "gold_clause_ids": clauses,
                          "user_response": names.apply(ur, nmap), "explanation": names.apply(expl, nmap),
                          "explanation_is_family_template": expl in template_texts, "tier": tier,
                          "input": names.apply(inp, nmap), "name_map": nmap})

    missing = set(decisions) - seen_decisions
    if missing:
        raise SystemExit(f"decisions.json names cases that have no review: {sorted(missing)}")

    OUT.mkdir(exist_ok=True)
    for name, rows in (("human_labels.jsonl", final), ("pending.jsonl", pending)):
        with open(OUT / name, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    tiers = Counter(r["tier"] for r in final)
    mix = {t: dict(Counter(r["gold_decision"] for r in final if r["tier"] == t)) for t in sorted(tiers)}
    mix["all"] = dict(Counter(r["gold_decision"] for r in final))
    finals = {t: dict(Counter(r["gold_final_action"] for r in final if r["tier"] == t)) for t in sorted(tiers)}
    suites = {t: dict(Counter(r["suite"] for r in final if r["tier"] == t)) for t in sorted(tiers)}
    rstats = {}
    for r, st in sorted(reviewer_stats.items()):
        n = st["reviews"]
        rstats[r] = {"reviews": n, "accepted": st["accepted"], "edited": st["edited"], "cannot_label": st["cannot_label"],
                     "fast_share": round(st["fast"] / n, 3), "same_as_suggestion_share": round(st["same_as_suggestion"] / n, 3)}
    for r in asg["annotators"]:
        rstats.setdefault(r, {"reviews": 0})
    summary = {
        "reviewed_cases": len(final) + len(pending), "final_cases": len(final), "pending_cases": len(pending),
        "tiers": dict(sorted(tiers.items())), "gold_decision_by_tier": mix, "gold_final_action_by_tier": finals,
        "suite_by_tier": suites, "reviewers": rstats,
        "double_reviewed_agreement": {
            "n_cases": len(pair_units),
            "percent_agreement_decision": round(sum(x == y for x, y in pair_units) / len(pair_units), 3) if pair_units else None,
            "krippendorff_alpha_decision": krippendorff_alpha(pair_units),
            "cohen_kappa_decision": {"-".join(k): {"n": len(xs), "kappa": cohen_kappa(xs, ys)} for k, (xs, ys) in pair_kappa.items()}},
        "family_template_explanations": sum(r["explanation_is_family_template"] for r in final),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    write_decisions_md(decisions, final, pending)
    write_report(summary, asg)
    print(json.dumps({k: summary[k] for k in ("reviewed_cases", "final_cases", "pending_cases", "tiers")}))


def write_report(s: dict, asg: dict) -> None:
    t = s["tiers"]
    dec = ("ALLOW", "BLOCK", "ASK_USER", "ESCALATE")
    names = {"A": "two careful reviews agree", "B": "one careful review", "C": "only fast reviews (unchecked)",
             "T": "decided by the team"}
    ag = s["double_reviewed_agreement"]
    batches_done = defaultdict(list)
    for bid, b in sorted(asg["batches"].items()):
        n = sum(1 for r in b["reviewers"] if L.read_votes(r, bid))
        batches_done[n].append(bid[-2:])
    lines = [
        "# Human label dataset",
        "",
        f"**{s['final_cases']} of 2,000 cases have a final human label; {s['pending_cases']} wait for a team call"
        f" (see [DECISIONS.md](DECISIONS.md)); {2000 - s['reviewed_cases']} are not reviewed yet.**",
        "",
        "Built by `python human_label_dataset/build.py` from the reviews committed on the `labeling` branch.",
        "",
        "## Tiers",
        "",
        "| Tier | Meaning | Cases | ALLOW | BLOCK | ASK_USER | ESCALATE |",
        "|---|---|---|---|---|---|---|",
        *[f"| {k} | {names[k]} | {t.get(k, 0)} | " + " | ".join(str(s['gold_decision_by_tier'].get(k, {}).get(d, 0)) for d in dec)
          + " |" for k in ("A", "B", "T", "C")],
        f"| | **all** | **{s['final_cases']}** | " + " | ".join(str(s['gold_decision_by_tier']['all'].get(d, 0)) for d in dec) + " |",
        "",
        f"A review is *fast* when it was saved less than {FAST_SECONDS} s after the reviewer's previous save, too quick"
        " to read the case. Exception: " + ", ".join(sorted(EARLIER_SCHEMA_REVIEWERS)) + " labelled these cases"
        " earlier with the previous labelling schema and re-marked the same labels in the review tool, so those"
        " reviews count as careful.",
        "",
        "**For the final evaluation use tiers A + B + T.** Tier C labels are the suggested labels accepted without being"
        " read; treat them as unchecked until someone reviews them properly.",
        "",
        "## Reviewers",
        "",
        "| Reviewer | Reviews | Accepted | Edited | Can't label | Fast saves | Same as suggestion |",
        "|---|---|---|---|---|---|---|",
        *[f"| {r} | {v.get('reviews', 0)} | {v.get('accepted', '–')} | {v.get('edited', '–')} | {v.get('cannot_label', '–')} | "
          + (f"{v['fast_share']:.0%} | {v['same_as_suggestion_share']:.0%} |" if v.get("reviews") else "– | – |")
          for r, v in s["reviewers"].items()],
        "",
        f"Batches with both reviews: {', '.join(batches_done[2]) or 'none'}. With one: {', '.join(batches_done[1]) or 'none'}."
        f" With none: {', '.join(batches_done[0]) or 'none'}.",
        "",
        "## Agreement (cases reviewed by both)",
        "",
        f"{ag['n_cases']} cases; decision agreement {ag['percent_agreement_decision']:.1%}, Krippendorff's α"
        f" {ag['krippendorff_alpha_decision']:.3f}. Agreement is inflated: almost every review accepts the same suggested"
        " label, so this mostly measures agreement with the suggestion, not two independent judgements.",
        "",
        "## Known issues",
        "",
        f"- {s['family_template_explanations']} final labels keep a suggested explanation that the suggestions reuse for"
        " different decisions (written per scenario family, not per case); `explanation_is_family_template` marks them."
        " The decision fields are what counts; check those explanations before using them as training targets.",
        "- Reviewer comments are kept in `reviewer_comments`, never inside `explanation`.",
        "",
        "## Name variation",
        "",
        "Every case in the source data uses the same people (the user is always Emma Johnson), which a model can learn"
        " as a shortcut. Each case's `input`, `explanation` and `user_response` therefore use their own set of names"
        " (`names.py`): consistent inside the case, first and last names mapped separately (so \"which Sarah?\" cases"
        " stay ambiguous), typos kept as typos, domains and company names unchanged. `name_map` holds the mapping, so"
        " it can be undone. Labels do not change, because no rule depends on a person's name.",
        "",
        "## Files",
        "",
        "| File | Content |",
        "|---|---|",
        "| `final/human_labels.jsonl` | one row per labelled case: gold fields, user reply (clean + noisy), explanation,"
        " tier, every review, reviewer comments, the case `input` (names varied) and `name_map` |",
        "| `final/pending.jsonl` | reviewed cases waiting for a call in `decisions.json` |",
        "| `final/summary.json` | all numbers in this report |",
        "| `decisions.json` / `DECISIONS.md` | the open calls with both labels, a recommendation and the reason |",
    ]
    (HERE / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_decisions_md(decisions: dict, final: list, pending: list) -> None:
    rows = {r["case_id"]: r for r in final + pending}
    lines = ["# Open calls", "",
             "Each item: what the reviewers said, my recommendation and why. Set `choice` in `decisions.json`",
             "(`recommended`, `suggestion`, a reviewer's name, or `drop`) and run `python human_label_dataset/build.py`.", ""]
    for cid, d in decisions.items():
        r = rows.get(cid, {})
        rec = d["recommended"]
        lines += [f"## {d['batch']} #{d['position']}: `{cid}`", "",
                  f"- **Flag:** {d['flag']}",
                  "- **Reviews:** " + "; ".join(
                      f"{who}: " + (f"can't label ({x.get('reason')}) {x.get('note')!r}" if x["status"] == "cannot_label"
                                    else f"{x['decision']} → {x['final_action']}")
                      for who, x in r.get("reviews", {}).items()),
                  f"- **Recommended:** {rec['decision']} → {rec['final_action']} (missing {rec['missing_evidence']}, "
                  f"decides {rec['required_authority']}): {rec['explanation']}",
                  f"- **Why:** {d['reason']}",
                  f"- **Your call:** " + (f"`{d['choice']}`" if d["choice"] else "not decided yet"), ""]
    (HERE / "DECISIONS.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
