import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from secgate.config import load_config  # noqa: E402
from secgate.data.cases import Case  # noqa: E402
from secgate.data.loaders import AgentDojoData  # noqa: E402
from secgate.evidence.context import ContextBuilder  # noqa: E402


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
    return {"role": "tool", "content": [{"type": "text", "content": text}], "tool_call": {"function": function,
                                                                                       "args": {}}}


@pytest.fixture
def make_case(builder):
    """Build a Case from a hand-written situation through the real context builder."""

    def _make(suite, prompt, function, args, outputs=(), injections=(), goal_match=False,
              scenario_id=None, pool="test"):
        msgs = [tool_msg(fn, text) for fn, text in outputs]
        gi, extras = builder.build("t|" + function, suite, prompt, {"function": function, "args": args}, [], msgs,
                                   injections=injections, goal_match=goal_match)
        return Case(input=gi, pool=pool, scenario_id=scenario_id, alt_provenance=extras["provenance"],
                    meta={"retrieved_ids": extras["retrieved_ids"]})

    return _make
