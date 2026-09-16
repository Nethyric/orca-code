"""Permission policy tests."""
import unittest

from orca.policy.permissions import Mode, Policy

READONLY = {"read_file", "grep", "glob", "ls", "todo"}


def check(policy, tool, **args):
    return policy.check(tool, args, readonly=tool in READONLY)


class TestModes(unittest.TestCase):
    def test_readonly_always_allowed(self):
        for mode in Mode:
            self.assertTrue(
                check(Policy(mode), "read_file", path="x.py").allowed)

    def test_plan_blocks_writes(self):
        d = check(Policy(Mode.PLAN), "write_file", path="x.py", content="")
        self.assertFalse(d.allowed)
        self.assertIn("read-only", d.reason)

    def test_yolo_allows_normal_bash(self):
        self.assertTrue(
            check(Policy(Mode.YOLO), "bash", command="ls -la").allowed)

    def test_yolo_still_blocks_destructive(self):
        for cmd in ("rm -rf /", "rm -fr ~/project", "mkfs.ext4 /dev/sda1",
                    "dd if=/dev/zero of=/dev/sda", "shutdown now",
                    "git push origin main --force"):
            d = check(Policy(Mode.YOLO), "bash", command=cmd)
            self.assertFalse(d.allowed, cmd)

    def test_accept_edits_allows_writes_but_guards_bash(self):
        policy = Policy(Mode.ACCEPT_EDITS)
        self.assertTrue(check(policy, "edit_file", path="a",
                              old_string="x", new_string="y").allowed)
        d = check(policy, "bash", command="echo hi")
        self.assertFalse(d.allowed)  # no ask-hook configured -> safe deny

    def test_default_asks_via_callback(self):
        answers = {"bash": True, "write_file": False}
        policy = Policy(Mode.DEFAULT,
                        ask=lambda tool, summary: answers.get(tool, False))
        self.assertTrue(check(policy, "bash", command="ls").allowed)
        d = check(policy, "write_file", path="x", content="")
        self.assertFalse(d.allowed)
        self.assertIn("denied by user", d.reason)

    def test_default_without_prompt_denies_with_guidance(self):
        d = check(Policy(Mode.DEFAULT), "write_file", path="x", content="")
        self.assertFalse(d.allowed)
        self.assertIn("--yolo", d.reason)


if __name__ == "__main__":
    unittest.main()
