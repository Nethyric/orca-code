"""Usage / cost tracking tests, including the prompt-caching price model."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orca.usage import UsageTracker, CostLimitExceeded


class TestUsage(unittest.TestCase):
    def test_basic_record_and_cost(self):
        tracker = UsageTracker()
        tracker.record("anthropic", "claude-sonnet-4-5",
                       {"input": 1000, "output": 100, "cache_read": 0, "cache_write": 0})
        # sonnet 4.5: $3 in / $15 out per 1M
        expected = (1000 * 3 + 100 * 15) / 1_000_000
        self.assertAlmostEqual(tracker.total_cost, expected, places=9)
        self.assertTrue(tracker.has_pricing)
        self.assertIn("$", tracker.cost_text())

    def test_cache_pricing(self):
        tracker = UsageTracker()
        tracker.record("anthropic", "claude-sonnet-4-5",
                       {"input": 1000, "output": 0, "cache_read": 500, "cache_write": 200})
        # uncached 300*$3 + cached-read 500*$0.30 + cache-write 200*$3.75
        expected = (300 * 3 + 500 * 0.30 + 200 * 3.75) / 1_000_000
        self.assertAlmostEqual(tracker.total_cost, expected, places=9)

    def test_cache_hit_rate(self):
        tracker = UsageTracker()
        self.assertIsNone(tracker.cache_hit_rate)
        tracker.record("anthropic", "claude-sonnet-4-5",
                       {"input": 1000, "output": 0, "cache_read": 700, "cache_write": 0})
        self.assertAlmostEqual(tracker.cache_hit_rate, 0.7)
        self.assertIn("70% hit", tracker.cost_text())

    def test_unknown_pricing(self):
        tracker = UsageTracker()
        tracker.record("mock", "totally-unknown-model", {"input": 10, "output": 5,
                                                         "cache_read": 0, "cache_write": 0})
        self.assertFalse(tracker.has_pricing)
        self.assertEqual(tracker.total_cost, 0.0)
        self.assertIn("cost n/a", tracker.cost_text())

    def test_summary_rows_shape(self):
        tracker = UsageTracker()
        tracker.record("anthropic", "claude-sonnet-4-5",
                       {"input": 100, "output": 10, "cache_read": 40, "cache_write": 0})
        rows = tracker.summary_rows()
        self.assertEqual(len(rows), 1)
        key, tin, tout, tread, label = rows[0]
        self.assertEqual(tin, 100)
        self.assertEqual(tread, 40)
        self.assertTrue(label.startswith("$"))

    def test_guard(self):
        tracker = UsageTracker(max_cost_usd=0.001)
        tracker.record("anthropic", "claude-opus-4-5",
                       {"input": 1000, "output": 1000, "cache_read": 0, "cache_write": 0})
        # 1000*5 + 1000*25 = 0.03 USD > 0.001 cap
        with self.assertRaises(CostLimitExceeded):
            tracker.guard()

    def test_guard_without_cap(self):
        tracker = UsageTracker(max_cost_usd=None)
        tracker.record("anthropic", "claude-sonnet-4-5",
                       {"input": 10_000_000, "output": 0, "cache_read": 0, "cache_write": 0})
        tracker.guard()  # must not raise


if __name__ == "__main__":
    unittest.main()
