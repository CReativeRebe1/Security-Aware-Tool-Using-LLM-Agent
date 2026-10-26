import itertools
import random

import pytest

from secgate.agent.extract import proposals_from_trace
from secgate.data.ground_truth import matches_task
from secgate.data.loaders import message_text
from secgate.data.splits import LeakageError, Splits
from secgate.evidence.tools import REGISTRY, STATE_CHANGING


def test_pool_sizes_and_disjointness(data):
    s = Splits(data)
    train, dev, test = (set(s.scenarios_in(p)) for p in ("train", "dev", "test"))
    train_only = set(s.scenarios_in("train_only"))
    assert len(train) == 276 and len(test) == 142
    assert dev <= train and train_only == train - dev
    assert not train & test


def test_leakage_guard(data):
    s = Splits(data)
    test_sid = s.scenarios_in("test")[0]
    dev_sid = s.scenarios_in("dev")[0]
    s.assert_pool(test_sid, "test")
    s.assert_pool(dev_sid, "train")
    with pytest.raises(LeakageError):
        s.assert_pool(test_sid, "train")
    with pytest.raises(LeakageError):
        s.assert_pool(dev_sid, "train_only")
    s.assert_pool({"pool": "test"}, "test")            # decision-only case with an explicit tag
    with pytest.raises(LeakageError):
        s.assert_pool({"pool": "test"}, "train")


def test_registry_covers_every_tool(data):
    names = {name for _, name in data.tools}
    assert names == set(REGISTRY)
    assert len(STATE_CHANGING) == 15


def test_user_task_ground_truth_matches_itself(data):
    for (suite, tid), t in data.user_tasks.items():
        for gt in t["ground_truth_calls"]:
            assert matches_task(gt, t), (suite, tid, gt["function"])
    t = data.user_tasks[("banking", "user_task_0")]
    assert not matches_task({"function": "send_money", "args": {"recipient": "US133000000121212121212"}}, t)


def test_extraction_reproduces_dataset_rows(data):
    random.seed(3)
    traces = list(itertools.islice(data.iter_traces(lambda t: t["user_task_id"] and t["tool_calls"]), 300))
    for tr in random.sample(traces, 20):
        mine = proposals_from_trace(tr, next(message_text(m) for m in tr["messages"] if m["role"] == "user"),
                                    data.user_tasks.get((tr["suite"], tr["user_task_id"])), None)
        ref = list(data.iter_proposals(lambda r: r["trace_id"] == tr["trace_id"]))
        assert [(r["message_index"], r["step"], r["proposed_call"]["function"]) for r in mine] == \
            [(r["message_index"], r["step"], r["proposed_call"]["function"]) for r in ref]
        assert [r["prior_calls"] for r in mine] == [r["prior_calls"] for r in ref]
