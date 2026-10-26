import pytest

from sagate.data.splits import LeakageError, Splits


def test_pool_counts_match_frozen_split(data):
    s = Splits(data)
    train, test = s.scenarios_in("train"), s.scenarios_in("test")
    assert len(train) == 276 and len(test) == 142
    assert not set(train) & set(test)
    dev = s.scenarios_in("dev")
    assert dev and set(dev) <= set(train)
    excluded = [sid for sid in data.scenarios if s.pool_of(sid) == "excluded"]
    assert len(excluded) == 342


def test_assert_pool_guards(data):
    s = Splits(data)
    test_sid = s.scenarios_in("test")[0]
    train_sid = next(x for x in s.scenarios_in("train") if s.pool_of(x) == "train")
    s.assert_pool({"scenario_id": test_sid}, "test")
    s.assert_pool({"scenario_id": train_sid}, "train")
    with pytest.raises(LeakageError):
        s.assert_pool({"scenario_id": test_sid}, "train")
    with pytest.raises(LeakageError):
        s.assert_pool({"scenario_id": train_sid}, "test")
    dev_sid = s.scenarios_in("dev")[0]
    s.assert_pool({"scenario_id": dev_sid}, "train")
    with pytest.raises(LeakageError):
        s.assert_pool({"scenario_id": dev_sid}, "test")


def test_excluded_scenarios_never_pass(data):
    s = Splits(data)
    sid = next(x for x in data.scenarios if s.pool_of(x) == "excluded")
    for pool in ("train", "test", "dev"):
        with pytest.raises(LeakageError):
            s.assert_pool({"scenario_id": sid}, pool)


def test_decision_only_cases_use_pool_tag(data):
    s = Splits(data)
    s.assert_pool({"pool": "test"}, "test")
    with pytest.raises(LeakageError):
        s.assert_pool({"pool": "train"}, "test")
