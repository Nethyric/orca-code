"""Session tests: crash safety, isolation, export."""
import json
import unittest

from orca.runtime.sessions import Session, export_markdown

from tests.helpers import tmp_root


class TestSessions(unittest.TestCase):
    def setUp(self):
        self.dir = tmp_root("orca-sessions-")

    def test_append_and_load_roundtrip(self):
        s = Session(directory=self.dir)
        s.add_user("hello")
        s.add_assistant("hi there", tool_calls=[
            {"id": "c1", "name": "bash", "input": {"command": "ls"}}])
        loaded = Session.load(s.sid, self.dir)
        self.assertEqual(len(loaded.messages), 2)
        self.assertEqual(loaded.messages[0]["content"][0]["text"], "hello")

    def test_sessions_are_isolated_by_file(self):
        a = Session(directory=self.dir)
        b = Session(directory=self.dir)
        a.add_user("context for A only")
        b.add_user("context for B only")
        loaded_b = Session.load(b.sid, self.dir)
        texts = [blk.get("text") for m in loaded_b.messages
                 for blk in m["content"]]
        self.assertIn("context for B only", texts)
        self.assertNotIn("context for A only", texts)

    def test_torn_tail_line_does_not_lose_session(self):
        s = Session(directory=self.dir)
        s.add_user("important question")
        with (self.dir / f"{s.sid}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write('{"sid": "%s", "msg": {"role": "user", "con' % s.sid)
        loaded = Session.load(s.sid, self.dir)
        self.assertEqual(len(loaded.messages), 1)

    def test_every_line_carries_its_sid(self):
        s = Session(directory=self.dir)
        s.add_user("x")
        line = (self.dir / f"{s.sid}.jsonl").read_text(encoding="utf-8")
        record = json.loads(line.strip())
        self.assertEqual(record["sid"], s.sid)

    def test_list_sessions_previews(self):
        s = Session(directory=self.dir)
        s.add_user("find the auth flow please")
        items = Session.list(self.dir)
        self.assertEqual(items[0]["sid"], s.sid)
        self.assertIn("find the auth flow", items[0]["preview"])

    def test_export_markdown(self):
        s = Session()
        s.add_user("fix the bug")
        s.add_assistant("Fixed.")
        out = tmp_root("orca-export-") / "t.md"
        export_markdown(s.messages, out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("🧑 You", text)
        self.assertIn("🐋 Orca", text)
        self.assertIn("fix the bug", text)
        self.assertIn("Fixed.", text)


if __name__ == "__main__":
    unittest.main()
