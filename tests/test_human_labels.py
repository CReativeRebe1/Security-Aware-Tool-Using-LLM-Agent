from pathlib import Path

import pytest

from sagate.config import load_config
from sagate.data.cases import load_cases
from sagate.data.splits import LeakageError
from sagate.train.build_sft import assert_not_held_out

ANN = Path(__file__).resolve().parents[1] / "annotations"


def test_frozen_case_files_are_disjoint_by_family():
    pools = {p: load_cases(ANN / f) for p, f in (("train", "train_human.jsonl"), ("dev", "dev_cases.jsonl"),
                                                 ("test", "test_cases.jsonl"))}
    assert {p: len(c) for p, c in pools.items()} == {"train": 1049, "dev": 236, "test": 212}
    fam = {p: {c.meta["family"] for c in cs} for p, cs in pools.items()}
    assert not (fam["train"] & fam["dev"]) and not (fam["train"] & fam["test"]) and not (fam["dev"] & fam["test"])
    for p, cs in pools.items():
        assert all(c.pool == p and c.subset == "decision_only" and c.has_gold for c in cs)
        assert all(len(c.meta["retrieved_ids"]) == 8 and "inferred" in c.alt_provenance for c in cs)


def test_training_refuses_held_out_cases():
    annotations = load_config().path("annotations_dir")
    assert_not_held_out(load_cases(ANN / "train_human.jsonl"), annotations)
    with pytest.raises(LeakageError):
        assert_not_held_out(load_cases(ANN / "test_cases.jsonl")[:3], annotations)
