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


def test_train_only_pool_excludes_dev(data):
    s = Splits(data)
    dev_sid = s.scenarios_in("dev")[0]
    train_sid = next(x for x in s.scenarios_in("train") if s.pool_of(x) == "train")
    s.assert_pool({"scenario_id": train_sid}, "train_only")
    with pytest.raises(LeakageError):
        s.assert_pool({"scenario_id": dev_sid}, "train_only")
    assert not set(s.scenarios_in("train_only")) & set(s.scenarios_in("dev"))


def test_b0_merge_dedupes_retries_and_summarises(data, tmp_path):
    import json
    from sagate.agent.run_b0 import merge, trace_id
    s = Splits(data)
    sid = next(x for x in s.scenarios_in("test") if not x.endswith("|benign"))
    suite, ut, it = sid.split("|")
    tid = trace_id(suite, ut, "important_instructions", it)
    base = {"key": tid, "trace_id": tid, "suite": suite, "user_task_id": ut, "injection_task_id": it}
    shard = tmp_path / "traces_shard0.jsonl"
    shard.write_text(json.dumps(dict(base, utility=False, attack_succeeded=None, error="OOM")) + "\n"
                     + json.dumps(dict(base, utility=True, attack_succeeded=True, error=None)) + "\n"
                     + '{"key": "partial')                       # killed mid-write
    summary = merge([str(shard)], tmp_path, data)
    assert len((tmp_path / "traces.jsonl").read_text().splitlines()) == 1
    assert summary[f"test/{suite}"]["utility_rate"] == "1/1" and summary["test/all"]["asr"] == "1/1"


def test_read_jsonl_falls_back_to_decompressed_file(tmp_path):
    """Kaggle decompresses nested .gz files in uploaded datasets."""
    from sagate.data.loaders import read_jsonl
    (tmp_path / "rows.jsonl").write_text('{"a": 1}\n')
    assert list(read_jsonl(tmp_path / "rows.jsonl.gz")) == [{"a": 1}]
