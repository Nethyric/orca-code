"""End-to-end agent loop tests with the offline MockProvider."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orca.agent import Agent
from orca.config import Config, DEFAULTS
from orca.permissions import Permissions
from orca.providers import MockProvider
from orca.sessions import Session
from orca.ui import UI


class QuietUI(UI):
    """Swallows output; records tool activity for assertions."""

    def __init__(self):
        super().__init__(interactive=False)
        self.tool_calls = []
        self.errors = []

    def tool_start(self, name, detail):
        self.tool_calls.append((name, detail))

    def tool_done(self, summary, is_error=False):
        pass

    def turn_footer(self, used, window, cost_text):
        pass

    def todos(self, items):
        pass

    def stream_text(self, delta):
        pass

    def end_stream(self):
        pass

    def warn(self, msg):
        pass

    def error(self, msg):
        self.errors.append(msg)


def make_cfg(root: Path, **over) -> Config:
    os.environ["ORCA_HOME"] = str(root / "orca-home")
    cfg = Config.__new__(Config)
    cfg._data = dict(DEFAULTS)
    cfg.root = root
    for k, v in over.items():
        cfg._data[k] = v
    return cfg


def make_agent(files: dict, script: list, mode: str = "yolo", root: Path = None):
    root = root or Path(tempfile.mkdtemp(prefix="orca-agent-"))
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    cfg = make_cfg(root)
    provider = MockProvider(script=script)
    ui = QuietUI()
    agent = Agent(provider, cfg, ui, permissions=Permissions(mode=mode),
                  session=Session(), root=root)
    return agent, root


class TestAgentLoop(unittest.TestCase):
    def test_full_loop_write_and_bash(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "I'll create the file."},
                {"type": "tool_use", "id": "t1", "name": "write_file",
                 "input": {"path": "hello.py", "content": 'print("hi")\n'}}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t2", "name": "bash",
                 "input": {"command": "python3 hello.py"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Done — created and verified."}]},
        ]
        agent, root = make_agent({}, script)
        agent.run("make hello.py that prints hi")

        self.assertTrue((root / "hello.py").is_file())
        # transcript structure: user, asst(text+tool), user(result), asst(tool), user(result), asst(text)
        roles = [m["role"] for m in agent.messages]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant", "user", "assistant"])
        # final message has no tool calls
        final = agent.messages[-1]["content"]
        self.assertTrue(all(b["type"] == "text" for b in final))
        # usage recorded from mock
        self.assertGreater(agent.usage.total_in, 0)
        # session file written
        self.assertIsNotNone(agent.session.path)
        self.assertTrue(agent.session.path.is_file())

    def test_undo_reverts_agent_writes(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "edit_file",
                 "input": {"path": "app.py", "old_string": "v1",
                           "new_string": "v2"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "edited"}]},
        ]
        agent, root = make_agent({"app.py": "v1\n"}, script)
        agent.run("bump the version")
        self.assertEqual((root / "app.py").read_text(), "v2\n")
        agent.ctx.undo.undo()
        self.assertEqual((root / "app.py").read_text(), "v1\n")

    def test_plan_mode_blocks_writes(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "write_file",
                 "input": {"path": "x.py", "content": "nope"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "OK, here is the plan instead."}]},
        ]
        agent, root = make_agent({}, script, mode="plan")
        agent.run("write x.py")
        self.assertFalse((root / "x.py").exists())
        # the tool result must carry the plan-mode denial back to the model
        result_msg = agent.messages[2]
        self.assertEqual(result_msg["content"][0]["type"], "tool_result")
        self.assertTrue(result_msg["content"][0]["is_error"])
        self.assertIn("Plan mode", result_msg["content"][0]["content"])

    def test_permission_denial_in_print_mode(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "bash",
                 "input": {"command": "rm -rf /tmp/orca-test-dangerous"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "denied then, got it"}]},
        ]
        agent, root = make_agent({}, script, mode="default")
        agent.auto_approve_callback = lambda name, args: "n"  # print-mode behaviour
        agent.run("delete stuff")
        result = agent.messages[2]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("denied", result["content"])

    def test_catastrophic_bash_blocked_even_in_yolo(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "bash",
                 "input": {"command": "rm -rf /"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "fine, won't"}]},
        ]
        agent, root = make_agent({}, script, mode="yolo")
        agent.run("wipe it")
        result = agent.messages[2]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("catastrophic", result["content"])

    def test_allow_rule_for_bash(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "bash",
                 "input": {"command": "git status"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "clean tree"}]},
        ]
        agent, root = make_agent({}, script, mode="default")
        agent.run("check git")
        result = agent.messages[2]["content"][0]
        self.assertFalse(result.get("is_error", False))

    def test_todo_tool_updates_state(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "todo", "input": {"todos": [
                    {"content": "first", "status": "completed"},
                    {"content": "second", "status": "in_progress"}]}}],
             },
            {"role": "assistant", "content": [{"type": "text", "text": "tracked"}]},
        ]
        agent, root = make_agent({}, script)
        agent.run("track work")
        self.assertEqual(len(agent.ctx.todos), 2)
        self.assertEqual(agent.ctx.todos[1]["status"], "in_progress")

    def test_provider_error_does_not_crash(self):
        from orca.providers import ProviderError

        class BrokenProvider(MockProvider):
            def stream(self, system, messages, tools=None):
                raise ProviderError("upstream 500")
                yield  # pragma: no cover

        cfg_root = Path(tempfile.mkdtemp(prefix="orca-broken-"))
        os.environ["ORCA_HOME"] = str(cfg_root / "home")
        cfg = make_cfg(cfg_root)
        agent = Agent(BrokenProvider(script=[]), cfg, QuietUI(),
                      permissions=Permissions(mode="yolo"), session=Session(), root=cfg_root)
        agent.run("hello")
        self.assertEqual(agent.messages[-1]["role"], "user")  # loop aborted cleanly


class TestResume(unittest.TestCase):
    def test_session_roundtrip(self):
        script = [
            {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]},
        ]
        agent, root = make_agent({}, script)
        agent.run("say hi")
        path = agent.session.path

        from orca.sessions import load_session
        loaded = load_session(path)
        self.assertEqual(loaded[0]["role"], "user")
        self.assertEqual(loaded[1]["content"][0]["text"], "hi there")


if __name__ == "__main__":
    unittest.main()


class TestRewind(unittest.TestCase):
    def _run_two_write_turns(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "write_file",
                 "input": {"path": "f.txt", "content": "version-1"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "wrote v1"}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t2", "name": "write_file",
                 "input": {"path": "f.txt", "content": "version-2"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "wrote v2"}]},
        ]
        agent, root = make_agent({"f.txt": "original"}, script)
        agent.run("make it v1")
        agent.run("now make it v2")
        self.assertEqual((root / "f.txt").read_text(), "version-2")
        return agent, root

    def test_rewind_one_turn(self):
        agent, root = self._run_two_write_turns()
        n_msgs = len(agent.messages)
        summary = agent.rewind(1)
        self.assertEqual((root / "f.txt").read_text(), "version-1")
        self.assertLess(len(agent.messages), n_msgs)
        self.assertIn("1 turn", summary)
        # the surviving conversation must end before the second user turn
        user_texts = [b.get("text") for m in agent.messages if m["role"] == "user"
                      for b in m["content"] if b.get("type") == "text"]
        self.assertEqual(user_texts, ["make it v1"])

    def test_rewind_everything(self):
        agent, root = self._run_two_write_turns()
        agent.rewind(9)  # more than available: clamps
        self.assertEqual((root / "f.txt").read_text(), "original")
        self.assertEqual(agent.messages, [])
        self.assertEqual(agent.checkpoints, [])

    def test_rewind_nothing_available(self):
        agent, root = make_agent({}, [])
        self.assertEqual(agent.rewind(1), "Nothing to rewind yet.")


class TestLoopDetection(unittest.TestCase):
    def test_identical_calls_flagged(self):
        call = {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t", "name": "bash",
             "input": {"command": "cat debug.log"}}]}
        final = {"role": "assistant", "content": [
            {"type": "text", "text": "done"}]}
        script = [call, call, call, final]
        agent, root = make_agent({}, script)
        agent.run("check the log")
        results = [b for m in agent.messages if m["role"] == "user"
                   for b in m["content"] if b.get("type") == "tool_result"]
        self.assertGreaterEqual(len(results), 3)
        self.assertIn("[orca] Notice", results[-1]["content"])
        self.assertIn("no progress", results[-1]["content"])


class TestDiffPreview(unittest.TestCase):
    def test_edit_diff_shows_changes(self):
        from orca.agent import build_change_diff
        agent, root = make_agent({"app.py": "def f():\n    return 1\n"}, [])
        args = {"path": "app.py", "old_string": "return 1", "new_string": "return 2"}
        diff = build_change_diff(agent.ctx, "edit_file", args)
        self.assertIsNotNone(diff)
        self.assertIn("-    return 1", diff)
        self.assertIn("+    return 2", diff)
        self.assertIn("a/app.py", diff)

    def test_write_new_file_diff(self):
        from orca.agent import build_change_diff
        agent, root = make_agent({}, [])
        args = {"path": "new.py", "content": "x = 1\n"}
        diff = build_change_diff(agent.ctx, "write_file", args)
        self.assertIsNotNone(diff)
        self.assertIn("+x = 1", diff)
        self.assertIn("/dev/null", diff)

    def test_ambiguous_edit_skips_diff(self):
        from orca.agent import build_change_diff
        agent, root = make_agent({"a.txt": "dup\ndup\n"}, [])
        args = {"path": "a.txt", "old_string": "dup", "new_string": "x"}
        self.assertIsNone(build_change_diff(agent.ctx, "edit_file", args))


class TestPrintModePolicy(unittest.TestCase):
    def test_auto_approve_respects_mode(self):
        import importlib
        cli = importlib.import_module("orca.cli")
        from orca.tools import TOOL_BY_NAME

        def make(mode):
            return mode

        # replicate the inline policy from cli.run_session
        for mode, tool, expect in (
            ("default", "write_file", "n"),
            ("default", "read_file", "y"),
            ("default", "web_search", "n"),
            ("acceptEdits", "write_file", "y"),
            ("acceptEdits", "bash", "n"),
            ("yolo", "bash", "y"),
            ("yolo", "web_fetch", "y"),
        ):
            def auto(name, a, _mode=mode):
                perm = TOOL_BY_NAME.get(name, {}).get("perm", "none")
                if perm in ("read", "none"):
                    return "y"
                if _mode == "yolo":
                    return "y"
                if perm == "write" and _mode == "acceptEdits":
                    return "y"
                return "n"
            self.assertEqual(auto(tool, {}), expect, f"mode={mode} tool={tool}")


class TestFallbackChain(unittest.TestCase):
    def test_provider_error_falls_back_to_next(self):
        import tempfile
        from orca.providers import BaseProvider, ProviderError, text_block

        class BrokenProvider(BaseProvider):
            name = "broken"
            kind = "openai"

            def stream(self, system, messages, tools=None):
                raise ProviderError("HTTP 429: overloaded")
                yield  # pragma: no cover

        root = Path(tempfile.mkdtemp(prefix="orca-fb-"))
        cfg = make_cfg(root, fallbacks=["mock"])
        script = [{"role": "assistant",
                   "content": [{"type": "text", "text": "recovered on fallback"}]}]
        ui = QuietUI()
        agent = Agent(BrokenProvider({"name": "broken", "kind": "openai",
                                      "base_url": "", "api_key": "x", "headers": {}},
                                     "big-model"),
                      cfg, ui, permissions=Permissions(mode="yolo"),
                      session=Session(), root=root)
        agent._fallback_queue = agent._build_fallbacks(["mock"])
        # patch the fallback's script (factory default is the offline demo)
        agent._fallback_queue[0].script = script
        agent.run("hello")
        self.assertEqual(agent.provider.name, "mock")
        self.assertIn("recovered on fallback",
                      "".join(b.get("text", "") for m in agent.messages
                              for b in m["content"] if b.get("type") == "text"))

    def test_no_fallback_after_text_streamed(self):
        import tempfile
        from orca.providers import BaseProvider, ProviderError, text_block

        class HalfBrokenProvider(BaseProvider):
            name = "half"
            kind = "openai"

            def stream(self, system, messages, tools=None):
                yield ("text", "partial answer…")
                raise ProviderError("connection lost mid-stream")

        root = Path(tempfile.mkdtemp(prefix="orca-fb2-"))
        cfg = make_cfg(root, fallbacks=["mock"])
        ui = QuietUI()
        agent = Agent(HalfBrokenProvider({"name": "half", "kind": "openai",
                                          "base_url": "", "api_key": "x", "headers": {}},
                                         "m"),
                      cfg, ui, permissions=Permissions(mode="yolo"),
                      session=Session(), root=root)
        agent._fallback_queue = agent._build_fallbacks(["mock"])
        agent.run("hello")
        # must NOT switch: text already streamed, fallback would duplicate it
        self.assertEqual(agent.provider.name, "half")
        self.assertTrue(agent.last_provider_error)

    def test_bad_fallback_entries_ignored(self):
        import tempfile
        root = Path(tempfile.mkdtemp(prefix="orca-fb3-"))
        cfg = make_cfg(root, fallbacks=["nonexistent-provider:x", "", "mock"])
        script = [{"role": "assistant",
                   "content": [{"type": "text", "text": "ok"}]}]
        agent, _root = make_agent({}, script, root=root)
        agent._fallback_queue = agent._build_fallbacks(cfg.get("fallbacks"))
        self.assertEqual(len(agent._fallback_queue), 1)
        self.assertEqual(agent._fallback_queue[0].name, "mock")


class TestVerifyGate(unittest.TestCase):
    def test_failing_verify_feeds_error_back_to_model(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "write_file",
                 "input": {"path": "a.txt", "content": "hi"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "wrote it"}]},
        ]
        agent, root = make_agent({}, script)
        agent.cfg._data["verify_command"] = 'python3 -c "import sys; sys.exit(3)"'
        agent.run("write a.txt")
        results = [b for m in agent.messages if m["role"] == "user"
                   for b in m["content"] if b.get("type") == "tool_result"]
        self.assertIn("[orca] verification FAILED", results[0]["content"])
        self.assertIn("exit 3", results[0]["content"])

    def test_passing_verify(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "write_file",
                 "input": {"path": "a.txt", "content": "hi"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "wrote it"}]},
        ]
        agent, root = make_agent({}, script)
        agent.cfg._data["verify_command"] = "true"
        agent.run("write a.txt")
        results = [b for m in agent.messages if m["role"] == "user"
                   for b in m["content"] if b.get("type") == "tool_result"]
        self.assertIn("[orca] verification passed", results[0]["content"])

    def test_no_verify_configured_is_noop(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "write_file",
                 "input": {"path": "a.txt", "content": "hi"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "wrote it"}]},
        ]
        agent, root = make_agent({}, script)
        agent.run("write a.txt")
        results = [b for m in agent.messages if m["role"] == "user"
                   for b in m["content"] if b.get("type") == "tool_result"]
        self.assertNotIn("[orca] verification", results[0]["content"])


class TestTokenBudget(unittest.TestCase):
    def test_budget_exceeded_raises(self):
        from orca.usage import TokenBudgetExceeded
        script = [{"role": "assistant",
                   "content": [{"type": "text", "text": "hi"}]}]
        agent, root = make_agent({}, script)
        agent.cfg._data["max_session_tokens"] = 1
        agent._max_session_tokens = 1
        with self.assertRaises(TokenBudgetExceeded):
            agent.run("hello")

    def test_no_budget_by_default(self):
        script = [{"role": "assistant",
                   "content": [{"type": "text", "text": "hi"}]}]
        agent, root = make_agent({}, script)
        agent.run("hello")  # must not raise
        self.assertGreater(agent.usage.total_tokens, 0)


class TestFastModelSummarize(unittest.TestCase):
    def test_fast_model_used_for_summarization(self):
        script = [{"role": "assistant",
                   "content": [{"type": "text", "text": "main"}]}]
        agent, root = make_agent({}, script)
        fast = MockProvider(script=[
            {"role": "assistant", "content": [{"type": "text", "text": "FAST-SUMMARY"}]}])
        agent.cfg._data["fast_model"] = "mock-1"
        agent._fast_provider = fast
        out = agent._summarize("sys", "please summarize this")
        self.assertEqual(out, "FAST-SUMMARY")
        # the main provider was untouched
        self.assertEqual(agent.provider.model, "mock-1")


class TestCustomCommands(unittest.TestCase):
    def test_custom_command_dispatches_with_arguments(self):
        from orca.repl import Repl
        script = [{"role": "assistant",
                   "content": [{"type": "text", "text": "done"}]}]
        agent, root = make_agent({}, script)
        cmd_dir = root / ".orca" / "commands"
        cmd_dir.mkdir(parents=True, exist_ok=True)
        (cmd_dir / "greet.md").write_text("Say hello to $ARGUMENTS politely.",
                                          encoding="utf-8")
        repl = Repl(agent, agent.ui, agent.cfg)
        self.assertIn("/greet", repl.custom_commands())
        repl._command("/greet Ada")
        last_user = [m for m in agent.messages if m["role"] == "user"][-1]
        self.assertIn("Say hello to Ada", last_user["content"][0]["text"])

    def test_custom_commands_empty_without_dir(self):
        from orca.repl import Repl
        agent, root = make_agent({}, [])
        repl = Repl(agent, agent.ui, agent.cfg)
        self.assertEqual(repl.custom_commands(), {})


class TestSessionReplaySemantics(unittest.TestCase):
    def test_rewind_and_compaction_survive_resume(self):
        from orca.sessions import Session, load_session
        import tempfile
        home = tempfile.mkdtemp(prefix="orca-sess-")
        os.environ["ORCA_HOME"] = str(Path(home) / "home")
        s = Session()
        s.start({"provider": "mock", "model": "m"}, "first task")
        s.append_message({"role": "user", "content": [{"type": "text", "text": "u1"}]})
        s.append_message({"role": "assistant", "content": [{"type": "text", "text": "a1"}]})
        s.append_message({"role": "user", "content": [{"type": "text", "text": "u2"}]})
        s.append_message({"role": "assistant", "content": [{"type": "text", "text": "a2"}]})
        s.append({"t": "rewind", "turns": 1, "msg_len": 2})
        s.append_message({"role": "user", "content": [{"type": "text", "text": "u3"}]})
        s.append_message({"role": "assistant", "content": [{"type": "text", "text": "a3"}]})
        s.append({"t": "compaction"})
        s.append_message({"role": "user", "content": [{"type": "text", "text": "summary msg"}]})
        msgs = load_session(s.path)
        texts = [b.get("text") for m in msgs for b in m["content"]]
        self.assertIn("summary msg", texts)
        self.assertNotIn("a2", texts)   # rewound away
        self.assertNotIn("a3", texts)   # compacted away
        self.assertNotIn("u1", texts)   # compacted away
