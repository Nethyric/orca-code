import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orca.config import Config, DEFAULTS
from orca.context import (ContextManager, estimate_messages, estimate_text,
                          _prune_tool_results, _split_turns)


def make_cfg(**over):
    cfg = Config.__new__(Config)
    cfg._data = dict(DEFAULTS)
    cfg.root = Path(".")
    for k, v in over.items():
        cfg._data[k] = v
    return cfg


def msg_user(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def msg_tool_call(id):
    return {"role": "assistant", "content": [
        {"type": "tool_use", "id": id, "name": "bash", "input": {"command": "ls"}}]}


def msg_tool_result(id, text):
    return {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": id, "content": text}]}


class TestEstimator(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(estimate_text(""), 0)
        self.assertGreater(estimate_text("x" * 380), 90)
        msgs = [msg_user("hello"), msg_tool_call("t1")]
        self.assertGreater(estimate_messages(msgs), 0)

    def test_calibration_scales(self):
        cfg = make_cfg()
        cm = ContextManager(cfg, "claude-sonnet-4-5")
        self.assertEqual(cm.window, 200_000)
        messages = [msg_user("hi")]
        cm.calibrate(1000, "sys", messages, "[]")
        self.assertGreater(cm.calibration, 0.5)
        used = cm.used("sys", messages, "[]")
        self.assertGreater(used, 0)


class TestSplit(unittest.TestCase):
    def test_tiny_budget_keeps_last_turns(self):
        messages = [msg_user("q1"), msg_tool_call("a1"), msg_tool_result("a1", "r1"),
                    msg_user("q2"), msg_tool_call("a2"), msg_tool_result("a2", "r2"),
                    msg_user("q3")]
        # budget so small even one turn overflows: only the final turn kept
        recent, older = _split_turns(messages, keep_budget_tokens=10)
        self.assertEqual(len(older), 6)
        self.assertEqual(recent[0]["content"][0]["text"], "q3")
        # budget that fits the last two turns: q1's turn gets compacted away
        recent, older = _split_turns(messages, keep_budget_tokens=50)
        self.assertEqual(len(older), 3)                          # q1 turn compacted away
        self.assertEqual(recent[0]["content"][0]["text"], "q2")  # clean turn boundary
        self.assertEqual(recent[-1]["content"][0]["text"], "q3")
        self.assertEqual(recent[0]["role"], "user")

    def test_big_budget_keeps_more(self):
        messages = [msg_user("q1"), msg_tool_call("a1"), msg_tool_result("a1", "r1"),
                    msg_user("q2")]
        recent, older = _split_turns(messages, keep_budget_tokens=10**9)
        self.assertEqual(len(recent), 4)
        self.assertEqual(older, [])

    def test_single_turn_not_split(self):
        messages = [msg_user("q1"), msg_tool_call("a1")]
        recent, older = _split_turns(messages, keep_budget_tokens=10)
        self.assertEqual(older, [])
        self.assertEqual(recent, messages)

    def test_tool_result_is_not_a_turn_start(self):
        from orca.context import _turn_start_indices
        messages = [msg_user("q1"), msg_tool_call("a1"), msg_tool_result("a1", "r1"),
                    msg_user("q2")]
        self.assertEqual(_turn_start_indices(messages), [0, 3])


class TestPrune(unittest.TestCase):
    def test_prunes_big_results_only(self):
        messages = [msg_tool_result("t1", "x" * 5000), msg_tool_result("t2", "short")]
        pruned, n = _prune_tool_results(messages, limit=800)
        self.assertEqual(n, 1)
        self.assertIn("pruned", pruned[0]["content"][0]["content"])
        self.assertEqual(pruned[1]["content"][0]["content"], "short")


class TestCompaction(unittest.TestCase):
    def test_compact_replaces_old_turns_with_summary(self):
        cfg = make_cfg(keep_recent=0.0005)  # tiny keep-budget → real split
        cm = ContextManager(cfg, "claude-sonnet-4-5")
        messages = []
        for i in range(6):
            messages.append(msg_user(f"question number {i} " + "x" * 200))
            messages.append(msg_tool_call(f"t{i}"))
            messages.append(msg_tool_result(f"t{i}", "result " * 200))
        messages.append(msg_user("final question"))
        tools_json = "[]"

        calls = []

        def summarizer(system, prompt):
            calls.append((system, prompt))
            return "SUMMARY: the user asked 6 things."

        out = cm.compact("SYS", messages, tools_json, summarizer)
        self.assertEqual(len(calls), 1)
        self.assertIn("SUMMARY", out[0]["content"][0]["text"])
        # the verbatim recent part must survive
        joined = [b.get("text", "") for m in out for b in m["content"] if b.get("type") == "text"]
        self.assertTrue(any("final question" in t for t in joined))
        self.assertLess(len(out), len(messages) + 1)
        self.assertEqual(cm.compactions, 1)

    def test_summarizer_failure_falls_back(self):
        cfg = make_cfg(keep_recent=0.0005)
        cm = ContextManager(cfg, "claude-sonnet-4-5")
        messages = []
        for i in range(4):
            messages.append(msg_user(f"question number {i}"))
            messages.append(msg_tool_call(f"t{i}"))
            messages.append(msg_tool_result(f"t{i}", "result"))
        messages.append(msg_user("last"))

        def summarizer(system, prompt):
            raise RuntimeError("summarizer exploded")

        out = cm.compact("SYS", messages, "[]", summarizer)
        self.assertIn("Compaction fallback", out[0]["content"][0]["text"])

    def test_maybe_compact_threshold(self):
        cfg = make_cfg(auto_compact=True, compact_threshold=0.5)
        cm = ContextManager(cfg, "claude-sonnet-4-5")
        self.assertFalse(cm.should_compact(1000))
        self.assertTrue(cm.should_compact(cm.window))  # 100% > 50%

    def test_should_compact_disabled(self):
        cfg = make_cfg(auto_compact=False)
        cm = ContextManager(cfg, "claude-sonnet-4-5")
        self.assertFalse(cm.should_compact(cm.window * 2))


class TestBreakdown(unittest.TestCase):
    def test_breakdown_categories(self):
        cfg = make_cfg()
        cm = ContextManager(cfg, "claude-sonnet-4-5")
        messages = [
            msg_user("hello"),
            {"role": "assistant", "content": [
                {"type": "text", "text": "working"},
                {"type": "tool_use", "id": "t", "name": "bash", "input": {"command": "ls"}}]},
            msg_tool_result("t", "output"),
        ]
        parts = cm.breakdown("SYSTEM", messages, '[{"tools": 1}]')
        self.assertEqual(sum(parts.values()), cm.used("SYSTEM", messages, '[{"tools": 1}]'))
        self.assertIn("tool results", parts)
        self.assertIn("assistant", parts)
        self.assertIn("overhead", parts)


if __name__ == "__main__":
    unittest.main()


class TestCompactionExtras(unittest.TestCase):
    def test_extra_context_lands_in_summary_message(self):
        cfg = make_cfg(keep_recent=0.0005)
        cm = ContextManager(cfg, "claude-sonnet-4-5")
        messages = []
        for i in range(4):
            messages.append(msg_user(f"question {i}"))
            messages.append(msg_tool_call(f"t{i}"))
            messages.append(msg_tool_result(f"t{i}", "result"))
        messages.append(msg_user("last"))
        out = cm.compact("SYS", messages, "[]", lambda s, p: "SUMMARY",
                         extra_context="Current task list:\n- [>] fix the bug")
        text = out[0]["content"][0]["text"]
        self.assertIn("SUMMARY", text)
        self.assertIn("fix the bug", text)
        self.assertIn("task list", text)
