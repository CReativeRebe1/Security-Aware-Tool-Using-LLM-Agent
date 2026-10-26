"""Statistics (proposal §8): paired bootstrap CIs, exact McNemar, Holm–Bonferroni, Krippendorff's α (nominal),
Cohen's κ. Pure Python + numpy so it runs anywhere."""

from __future__ import annotations

import math
from collections import Counter
from itertools import combinations
from typing import Hashable, Sequence

import numpy as np


def paired_bootstrap(a: Sequence[float], b: Sequence[float], n_resamples: int = 10_000, seed: int = 42,
                     alpha: float = 0.05) -> dict:
    """CI for mean(a) - mean(b) over paired per-case values (e.g. 0/1 success)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if a.shape != b.shape or a.size == 0:
        raise ValueError("a and b must be non-empty and paired")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(n_resamples, a.size))
    diffs = a[idx].mean(1) - b[idx].mean(1)
    lo, hi = np.quantile(diffs, [alpha / 2, 1 - alpha / 2])
    return {"diff": float(a.mean() - b.mean()), "ci_low": float(lo), "ci_high": float(hi), "n": int(a.size)}


def mcnemar_exact(a: Sequence[bool], b: Sequence[bool]) -> dict:
    """Exact (binomial) McNemar test on paired binary outcomes."""
    n01 = sum(bool(x) and not bool(y) for x, y in zip(a, b))   # a right, b wrong
    n10 = sum(not bool(x) and bool(y) for x, y in zip(a, b))
    n = n01 + n10
    if n == 0:
        return {"b01": n01, "b10": n10, "p_value": 1.0}
    k = min(n01, n10)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return {"b01": n01, "b10": n10, "p_value": min(1.0, 2 * p)}


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> dict[str, dict]:
    """Holm–Bonferroni step-down adjustment."""
    order = sorted(pvalues, key=pvalues.get)
    m = len(order)
    out, running = {}, 0.0
    for i, key in enumerate(order):
        adj = min(1.0, (m - i) * pvalues[key])
        running = max(running, adj)
        out[key] = {"p": pvalues[key], "p_holm": running, "reject": running <= alpha}
    return out


def cohen_kappa(x: Sequence[Hashable], y: Sequence[Hashable]) -> float | None:
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if not pairs:
        return None
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n ** 2
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def krippendorff_alpha_nominal(units: Sequence[Sequence[Hashable]]) -> float | None:
    """α for nominal data. `units` = per case, the labels given by whichever annotators labelled it."""
    units = [[v for v in u if v is not None] for u in units]
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None
    coincidence: Counter = Counter()
    for u in units:
        m = len(u)
        for i, j in ((i, j) for i in range(m) for j in range(m) if i != j):
            coincidence[(u[i], u[j])] += 1 / (m - 1)
    n_c = Counter()
    for (c, _), w in coincidence.items():
        n_c[c] += w
    n = sum(n_c.values())
    d_o = sum(w for (c, k), w in coincidence.items() if c != k)
    d_e = sum(n_c[c] * n_c[k] for c in n_c for k in n_c if c != k) / (n - 1)
    return 1.0 if d_e == 0 else 1 - d_o / d_e


def pairwise_kappa(labels: dict[str, dict[str, Hashable]]) -> dict[tuple[str, str], dict]:
    """labels[annotator][case_id] -> label. κ for every annotator pair over their shared cases."""
    out = {}
    for a, b in combinations(sorted(labels), 2):
        shared = sorted(set(labels[a]) & set(labels[b]))
        if shared:
            out[(a, b)] = {"n": len(shared),
                           "kappa": cohen_kappa([labels[a][k] for k in shared], [labels[b][k] for k in shared])}
    return out
