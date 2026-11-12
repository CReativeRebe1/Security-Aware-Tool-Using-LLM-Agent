import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sagate.config import load_config  # noqa: E402
from sagate.data.cases import Case  # noqa: E402
from sagate.data.loaders import AgentDojoData  # noqa: E402
from sagate.evidence.context_builder import ContextBuilder  # noqa: E402
from sagate.gate.schema import GateInput  # noqa: E402


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def data(cfg):
    return AgentDojoData(cfg.data_dir)


@pytest.fixture(scope="session")
def builder(cfg, data):
    return ContextBuilder(cfg, data)


def tool_msg(function: str, text: str) -> dict:
    return {"role": "tool", "content": [{"type": "text", "content": text}],
            "tool_call": {"function": function, "args": {}}, "error": None}


@pytest.fixture
def make_case(builder):
    """Build a Case from a hand-written conversation (no trace file needed)."""

    def _make(suite, prompt, call, tool_outputs=(), injections=(), scenario_id=None, case_id="t|1",
              prior_calls=()):
        msgs = [{"role": "user", "content": [{"type": "text", "content": prompt}]}]
        msgs += [tool_msg(fn, txt) for fn, txt in tool_outputs]
        gi, extras = builder.build(case_id, suite, prompt, call, list(prior_calls), msgs, None,
                                   injections=injections)
        return Case(input=gi, pool="test", scenario_id=scenario_id, alt_provenance=extras["provenance"],
                    meta={"retrieved_ids": extras["retrieved_ids"]})

    return _make


def minimal_input(**kw) -> GateInput:
    base = dict(case_id="x", suite="banking", user={"principal_id": "emma", "prompt": "p"},
                proposed_call={"function": "send_money", "args": {"recipient": "X"}, "state_changing": True,
                               "action": "transfer"})
    base.update(kw)
    return GateInput(**base)
