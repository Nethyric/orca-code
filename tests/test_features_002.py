"""Tests for the 0.0.2 feature round: task subagents, retry+jitter,
lifecycle hooks, output styles, and markdown export."""
import io
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orca.agent import Agent, OUTPUT_STYLES                     # noqa: E402
from orca.config import Config, ConfigError                     # noqa: E402
from orca.permissions import Permissions                        # noqa: E402
from orca.providers import MockProvider, Transport, ProviderError  # noqa: E402
from orca.sessions import Session, export_markdown              # noqa: E402
from orca.ui import UI                                          # noqa: E402

from tests.test_agent import make_cfg, QuietUI                   # noqa: E402


def make_agent_with_factory(script, factory, **kw):
    root = Path(tempfile.mkdtemp(prefix="orca-task-"))
    cfg = make_cfg(root)
    for key, value in kw.pop("cfg_overrides", {}).items():
        cfg.set(key, value)
    agent = Agent(MockProvider(script=script), cfg, QuietUI(),
                  permissions=Permissions(mode="yolo"),
                  session=Session(), root=root,
                  provider_factory=factory, **kw)
    return agent, root


class TestTaskSubagent(unittest.TestCase):
    def _sub_script(self):
        return [{"role": "assistant", "content": [
            {"type": "text", "text": "SUBREPORT: 3 files use the auth flow."}]}]

    def test_task_runs_subagent_and_returns_report(self):
        script = [
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "t1", "name": "task",
                 "input": {"prompt": "find the auth flow", "profile": "explore"}}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Report received."}]},
        ]
        agent, root = make_agent_with_factory(
            script, lambda: MockProvider(script=self._sub_script()))
        agent.run("research the auth flow")
        # the tool result must carry the subagent's report back to the parent
        results = [b for m in agent.messages for b in m.get("content", [])
                   if b.get("type") == "tool_result"]
        self.assertTrue(any("SUBREPORT" in str(b.get("content")) for b in results))
        self.assertEqual(agent.messages[-1]["content"][0]["text"], "Report received.")

    def test_subagent_cannot_spawn_subagents(self):
        """Depth cap: a subagent's own task call must be refused."""
        script = [{"role": "assistant", "content": [
            {"type": "text", "text": "done"}]}]
        agent, _ = make_agent_with_factory(
            script, lambda: MockProvider(script=[]), task_depth=1)
        result = agent._execute({"name": "task",
                                 "input": {"prompt": "nested?"}})
        self.assertTrue(result.get("is_error"))
        self.assertIn("cannot spawn further subagents",
                      str(result.get("content")))

    def test_explore_profile_has_no_write_tools(self):
        script = [{"role": "assistant", "content": [
            {"type": "text", "text": "x"}]}]
        agent, _ = make_agent_with_factory(
            script, lambda: MockProvider(script=self._sub_script()))
        # simulate what _run_task builds for explore
        from orca import tools as toolmod
        sub = Agent(MockProvider(script=self._sub_script()), agent.cfg, QuietUI(),
                    permissions=Permissions(mode="yolo"), session=Session(),
                    root=agent.root, allowed_tools=toolmod.EXPLORE_TOOLS)
        names = {s["name"] for s in sub._tool_specs()}
        self.assertNotIn("write_file", names)
        self.assertNotIn("edit_file", names)
        self.assertNotIn("bash", names)
        self.assertNotIn("task", names)
        self.assertIn("read_file", names)
        # full agent sees everything
        self.assertIn("task", {s["name"] for s in agent._tool_specs()})

    def test_task_requires_prompt(self):
        script = [{"role": "assistant", "content": [
            {"type": "text", "text": "done"}]}]
        agent, _ = make_agent_with_factory(
            script, lambda: MockProvider(script=self._sub_script()))
        result = agent._execute({"name": "task", "input": {}})
        self.assertIn("requires 'prompt'", str(result.get("content", "")))


class TestRetryWithJitter(unittest.TestCase):
    def _sse(self, text):
        return f'data: {{"choices":[{{"delta":{{"content":"{text}"}}}}]}}'.encode()

    def test_retries_429_then_succeeds(self):
        calls = {"n": 0}
        sleeps = []

        def fake_urlopen(req, timeout=600):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise urllib.error.HTTPError(
                    str(req.full_url), 429, "Too Many Requests",
                    {}, io.BytesIO(b"rate limited"))
            return io.BytesIO(b"data: [DONE]\n\n")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             mock.patch("time.sleep", side_effect=sleeps.append):
            out = list(Transport().post("http://x", {}, {"m": 1}))
        self.assertEqual(calls["n"], 3)
        self.assertEqual(len(sleeps), 2)           # 2 retries before success
        self.assertTrue(all(s >= 2 for s in sleeps))  # backoff base preserved

    def test_gateway_io_timeout_body_is_retried(self):
        """400 with 'i/o timeout' body is a gateway hiccup, not a client bug."""
        calls = {"n": 0}

        def fake_urlopen(req, timeout=600):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    str(req.full_url), 400, "Bad Request",
                    {}, io.BytesIO(b"failed to read body: i/o timeout"))
            return io.BytesIO(b"data: [DONE]\n\n")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             mock.patch("time.sleep"):
            list(Transport().post("http://x", {}, {"m": 1}))
        self.assertEqual(calls["n"], 2)

    def test_real_client_errors_are_not_retried(self):
        def fake_urlopen(req, timeout=600):
            raise urllib.error.HTTPError(
                str(req.full_url), 401, "Unauthorized",
                {}, io.BytesIO(b"invalid api token"))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(ProviderError):
                list(Transport().post("http://x", {}, {"m": 1}))


class TestHooks(unittest.TestCase):
    def _agent(self, hooks, files=None):
        root = Path(tempfile.mkdtemp(prefix="orca-hook-"))
        for rel, content in (files or {}).items():
            (root / rel).write_text(content, encoding="utf-8")
        cfg = make_cfg(root)
        cfg.set("hooks", hooks)
        agent = Agent(MockProvider(script=[]), cfg, QuietUI(),
                      permissions=Permissions(mode="yolo"),
                      session=Session(), root=root)
        return agent, root

    def test_after_edit_hook_runs_and_output_tagged(self):
        agent, root = self._agent({"after_edit": "echo formatted:%file"})
        result = agent._execute({"name": "write_file", "input": {
            "path": "a.py", "content": "x = 1\n"}})
        content = str(result.get("content", ""))
        self.assertIn("[hook] formatted:a.py", content)
        self.assertTrue((root / "a.py").is_file())

    def test_before_bash_hook_can_block(self):
        agent, root = self._agent({"before_bash": "exit 1"})
        result = agent._execute({"name": "bash", "input": {
            "command": "echo should-not-run"}})
        self.assertTrue(result.get("is_error"))
        self.assertIn("blocked by before_bash hook", str(result.get("content")))

    def test_no_hooks_configured_is_noop(self):
        agent, root = self._agent({})
        result = agent._execute({"name": "write_file", "input": {
            "path": "b.py", "content": "y = 2\n"}})
        self.assertNotIn("[hook]", str(result.get("content")))


class TestOutputStyle(unittest.TestCase):
    def test_style_directive_in_system_prompt(self):
        root = Path(tempfile.mkdtemp(prefix="orca-style-"))
        cfg = make_cfg(root)
        cfg.set("output_style", "concise")
        agent = Agent(MockProvider(script=[]), cfg, QuietUI(),
                      permissions=Permissions(mode="yolo"),
                      session=Session(), root=root)
        self.assertIn("Style: concise", agent.system_prompt())
        self.assertNotIn("Style: verbose", agent.system_prompt())

    def test_no_style_by_default(self):
        root = Path(tempfile.mkdtemp(prefix="orca-style-"))
        cfg = make_cfg(root)
        agent = Agent(MockProvider(script=[]), cfg, QuietUI(),
                      permissions=Permissions(mode="yolo"),
                      session=Session(), root=root)
        self.assertNotIn("Style:", agent.system_prompt())


class TestExportMarkdown(unittest.TestCase):
    def test_export_writes_readable_transcript(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "fix the bug"}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Looking."},
                {"type": "tool_use", "id": "t1", "name": "read_file",
                 "input": {"path": "calc.py"}}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": "1 │ def divide"}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Fixed."}]},
        ]
        out = Path(tempfile.mkdtemp()) / "session.md"
        export_markdown(messages, out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("## 🧑 You", text)
        self.assertIn("## 🐋 Orca", text)
        self.assertIn("`◆ read_file(", text)
        self.assertIn("↳", text)
        self.assertIn("Fixed.", text)


if __name__ == "__main__":
    unittest.main()
