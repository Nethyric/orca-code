"""Shared test fixtures: scripted agents, temp roots."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orca.core.budget import Budget, Usage            # noqa: E402
from orca.core.events import Bus, Recorder           # noqa: E402
from orca.core.loop import Agent, AgentConfig        # noqa: E402
from orca.policy.permissions import Mode, Policy     # noqa: E402
from orca.providers.provider import MockProvider, Reply  # noqa: E402
from orca.runtime.hooks import HookRunner            # noqa: E402
from orca.tools.builtin import register_builtins     # noqa: E402
from orca.tools.registry import Registry             # noqa: E402
from orca.tools.sandbox import Sandbox               # noqa: E402


def tmp_root(prefix="orca-v2-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def make_agent(script=None, *, mode=Mode.YOLO, root=None, budget=None,
               hooks=None, depth=0, factory=None, ask=None,
               max_turns=8, allowed=None):
    root = root or tmp_root()
    sandbox = Sandbox(root)
    registry = Registry()
    register_builtins(registry, sandbox)
    policy = Policy(mode, ask=ask)
    bus = Bus()
    rec = Recorder()
    bus.subscribe(rec)
    agent = Agent(
        MockProvider(script), registry, policy, bus,
        budget=budget or Budget(), hooks=hooks,
        cfg=AgentConfig(max_turns=max_turns), depth=depth,
        subagent_factory=factory)
    agent.allowed_names = allowed
    agent.test_root = root
    agent.test_rec = rec
    return agent


def call(name, **kw):
    """A scripted tool call."""
    return {"id": kw.pop("id", "c1"), "name": name, "input": kw}


def reply(text="", calls=None, thinking="", stop="stop", usage=None):
    return Reply(text=text, thinking=thinking,
                 tool_calls=calls or [], usage=usage or Usage(10, 5, 1),
                 stop_reason=stop)
