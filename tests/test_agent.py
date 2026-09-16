"""Kernel tests: the loop, subagents, budget stops, auto-continue, hooks."""
import unittest

from orca.core.budget import Budget, Usage
from orca.policy.permissions import Mode
from orca.providers.provider import BaseProvider, ProviderError, Reply
from orca.runtime.hooks import HookRunner

from tests.helpers import call, make_agent, reply, tmp_root


class TestLoopBasics(unittest.TestCase):
    def test_full_write_and_bash_roundtrip(self):
        agent = make_agent(script=[
            reply(calls=[call("write_file", path="hello.py",
                              content='print("hi")\n')]),
            reply(calls=[call("bash", command="python3 hello.py")]),
            reply(text="Created and verified."),
        ])
        out = agent.run("make hello.py")
        self.assertEqual(out, "Created and verified.")
        self.assertTrue((agent.test_root / "hello.py").is_file())
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(roles, ["user", "assistant", "user",
                                 "assistant", "user", "assistant"])
        kinds = agent.test_rec.kinds()
        self.assertIn("tool_start", kinds)
        self.assertIn("tool_end", kinds)
        self.assertIn("text", kinds)

    def test_empty_script_finishes_gracefully(self):
        agent = make_agent(script=[])
        out = agent.run("anything")
        self.assertEqual(out, "done")  # MockProvider default reply

    def test_unknown_tool_is_an_error_result_not_a_crash(self):
        agent = make_agent(script=[
            reply(calls=[call("teleport", destination="moon")]),
            reply(text="ok"),
        ])
        agent.run("go")
        results = [b for m in agent.messages for b in m["content"]
                   if b.get("type") == "tool_result"]
        self.assertTrue(results[0]["is_error"])
        self.assertIn("unknown tool", results[0]["content"])

    def test_turn_limit_is_enforced(self):
        agent = make_agent(script=None, max_turns=2)
        agent.provider.script = [
            reply(calls=[call("bash", command="true")]) for _ in range(9)]
        agent.run("spin")
        self.assertIsNotNone(agent.stopped)
        self.assertIn("turn limit", agent.stopped)

    def test_every_reply_announces_budget(self):
        agent = make_agent(script=[reply(text="a"), reply(text="b")])
        agent.run("hi")
        # script pops one reply; second turn uses the default mock reply
        budget_events = agent.test_rec.of(__import__(
            "orca.core.events", fromlist=["EKind"]).EKind.budget)
        self.assertGreaterEqual(len(budget_events), 1)


class TestPermissionsInLoop(unittest.TestCase):
    def test_plan_mode_blocks_write_and_reports_to_model(self):
        agent = make_agent(script=[
            reply(calls=[call("write_file", path="x.py", content="1")]),
            reply(text="understood"),
        ], mode=Mode.PLAN)
        agent.run("write x")
        results = [b for m in agent.messages for b in m["content"]
                   if b.get("type") == "tool_result"]
        self.assertTrue(results[0]["is_error"])
        self.assertIn("blocked by permissions", results[0]["content"])
        self.assertFalse((agent.test_root / "x.py").exists())

    def test_destructive_command_blocked_even_in_yolo(self):
        agent = make_agent(script=[
            reply(calls=[call("bash", command="rm -rf /")]),
            reply(text="ok"),
        ], mode=Mode.YOLO)
        agent.run("clean everything")
        results = [b for m in agent.messages for b in m["content"]
                   if b.get("type") == "tool_result"]
        self.assertTrue(results[0]["is_error"])
        self.assertIn("destructive", results[0]["content"])


class TestAutoContinue(unittest.TestCase):
    def test_empty_reply_gets_nudged_once(self):
        agent = make_agent(script=[
            reply(text="", stop="length"),
            reply(text="resumed and finished"),
        ])
        out = agent.run("long task")
        self.assertEqual(out, "resumed and finished")
        nudges = [m for m in agent.messages if m["role"] == "user"
                  and "Continue exactly where you left off"
                  in str(m["content"])]
        self.assertEqual(len(nudges), 1)
        notices = agent.test_rec.of(__import__(
            "orca.core.events", fromlist=["EKind"]).EKind.notice)
        self.assertTrue(any("nudging" in e.data.get("message", "")
                            for e in notices))

    def test_nudges_are_bounded(self):
        agent = make_agent(script=[
            reply(text="", stop="length") for _ in range(5)])
        agent.run("loop forever")
        nudges = [m for m in agent.messages if m["role"] == "user"
                  and "Continue exactly" in str(m["content"])]
        self.assertEqual(len(nudges), 2)  # continue_limit


class TestBudgetStops(unittest.TestCase):
    def test_token_budget_stops_the_loop(self):
        agent = make_agent(script=[
            reply(calls=[call("bash", command="true")],
                  usage=Usage(input_tokens=10_000, output_tokens=10_000)),
            reply(text="never reached"),
        ], budget=Budget(max_tokens=5_000))
        out = agent.run("burn")
        self.assertIn("token budget", agent.stopped)
        errors = agent.test_rec.of(__import__(
            "orca.core.events", fromlist=["EKind"]).EKind.error)
        self.assertTrue(any(e.data.get("fatal") for e in errors))

    def test_subagent_shares_the_budget(self):
        shared = Budget(max_tokens=1_000)

        def factory(profile):
            return make_agent(script=[reply(
                text="sub-report",
                usage=Usage(input_tokens=900, output_tokens=900))])

        agent = make_agent(script=[
            reply(calls=[call("task", prompt="explore",
                              profile="explore")]),
            reply(text="done"),
        ], budget=shared, factory=factory)
        agent.run("delegate")
        # after the subagent's 1800 tokens, the shared budget is over
        self.assertIsNotNone(shared.exceeded())


class TestSubagents(unittest.TestCase):
    def test_task_returns_subagent_report(self):
        def factory(profile):
            sub = make_agent(script=[reply(text="SUBREPORT: 3 findings")])
            sub._seen_profile = profile
            return sub

        agent = make_agent(script=[
            reply(calls=[call("task", prompt="research auth",
                              profile="explore")]),
            reply(text="report received"),
        ], factory=factory)
        out = agent.run("research")
        self.assertEqual(out, "report received")
        results = [b for m in agent.messages for b in m["content"]
                   if b.get("type") == "tool_result"]
        self.assertIn("SUBREPORT", results[0]["content"])
        kinds = agent.test_rec.kinds()
        self.assertIn("task_start", kinds)
        self.assertIn("task_end", kinds)

    def test_nested_subagents_refused(self):
        agent = make_agent(script=[reply(text="x")], depth=1)
        result = agent._run_task({"prompt": "nest?"})
        self.assertTrue(result.is_error)
        self.assertIn("cannot spawn further", result.output)

    def test_task_without_prompt_is_rejected(self):
        agent = make_agent(script=[])
        result = agent._run_task({})
        self.assertTrue(result.is_error)
        self.assertIn("requires", result.output)

    def test_task_without_factory_reports_clearly(self):
        agent = make_agent(script=[])
        result = agent._run_task({"prompt": "do it"})
        self.assertTrue(result.is_error)
        self.assertIn("not available", result.output)

    def test_subagent_provider_failure_is_contained(self):
        class Boom(BaseProvider):
            name = "boom"
            model = "boom-1"

            def reply(self, messages, tools, system=""):
                raise ProviderError("upstream melted")

        from orca.core.loop import Agent, AgentConfig
        from orca.core.events import Bus
        from orca.policy.permissions import Policy
        from orca.tools.builtin import register_builtins
        from orca.tools.registry import Registry
        from orca.tools.sandbox import Sandbox
        root = tmp_root()
        reg = Registry()
        register_builtins(reg, Sandbox(root))
        sub = Agent(Boom(), reg, Policy(Mode.YOLO), Bus(),
                    cfg=AgentConfig(max_turns=4))  # raises on first reply

        def factory(profile):
            return sub

        agent = make_agent(script=[
            reply(calls=[call("task", prompt="x")]),
            reply(text="handled"),
        ], factory=factory)
        agent.run("delegate")
        results = [b for m in agent.messages for b in m["content"]
                   if b.get("type") == "tool_result"]
        self.assertTrue(results[0]["is_error"])
        self.assertIn("subagent failed", results[0]["content"])


class TestHooksInLoop(unittest.TestCase):
    def test_before_bash_veto_blocks_command(self):
        root = tmp_root("orca-hook-")
        hooks = HookRunner({"before_bash": "exit 1"}, root=root)
        agent = make_agent(script=[
            reply(calls=[call("bash", command="echo should-not-run")]),
            reply(text="ok"),
        ], root=root, hooks=hooks)
        agent.run("run it")
        results = [b for m in agent.messages for b in m["content"]
                   if b.get("type") == "tool_result"]
        self.assertTrue(results[0]["is_error"])
        self.assertIn("blocked by before_bash", results[0]["content"])

    def test_after_edit_output_reaches_the_model(self):
        root = tmp_root("orca-hook2-")
        hooks = HookRunner({"after_edit": "echo formatted:%file"}, root=root)
        agent = make_agent(script=[
            reply(calls=[call("write_file", path="a.py", content="x=1")]),
            reply(text="done"),
        ], root=root, hooks=hooks)
        agent.run("write it")
        results = [b for m in agent.messages for b in m["content"]
                   if b.get("type") == "tool_result"]
        self.assertIn("[hook] formatted:a.py", results[0]["content"])


class TestProviderFailure(unittest.TestCase):
    def test_provider_error_stops_cleanly(self):
        class Boom(BaseProvider):
            name = "boom"
            model = "boom-1"

            def reply(self, messages, tools, system=""):
                raise ProviderError("401: bad key")

        from orca.core.loop import Agent, AgentConfig
        from orca.core.events import Bus, Recorder
        from orca.policy.permissions import Policy
        from orca.tools.builtin import register_builtins
        from orca.tools.registry import Registry
        from orca.tools.sandbox import Sandbox
        root = tmp_root()
        reg = Registry()
        register_builtins(reg, Sandbox(root))
        bus = Bus()
        rec = Recorder()
        bus.subscribe(rec)
        agent = Agent(Boom(), reg, Policy(Mode.YOLO), bus,
                      cfg=AgentConfig(max_turns=4))
        out = agent.run("hello")
        self.assertIsNone(out)
        self.assertIn("bad key", agent.stopped)
        self.assertTrue(any(e.data.get("fatal") for e in rec.of(
            __import__("orca.core.events", fromlist=["EKind"]).EKind.error)))


if __name__ == "__main__":
    unittest.main()
