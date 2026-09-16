"""Budget tests: counting once, stopping hard."""
import unittest

from orca.core.budget import Budget, Usage, price_of


class TestUsage(unittest.TestCase):
    def test_cache_tokens_are_separate(self):
        u = Usage(input_tokens=100, output_tokens=50, cache_read=500)
        self.assertEqual(u.total_tokens, 150)  # cache is not input
        u.add(Usage(input_tokens=1, output_tokens=1, cache_read=1))
        self.assertEqual((u.input_tokens, u.output_tokens, u.cache_read),
                         (101, 51, 501))

    def test_cost_accumulates(self):
        u = Usage(cost_usd=0.5)
        u.add(Usage(cost_usd=0.25))
        self.assertAlmostEqual(u.cost_usd, 0.75)


class TestPricing(unittest.TestCase):
    def test_known_family_priced(self):
        cost = price_of("gpt-5.1", Usage(input_tokens=1_000_000,
                                         output_tokens=1_000_000))
        self.assertAlmostEqual(cost, 11.25)

    def test_unknown_model_is_free_not_wrong(self):
        self.assertEqual(
            price_of("mystery-model-x", Usage(1000, 1000)), 0.0)


class TestBudgetStops(unittest.TestCase):
    def test_cost_ceiling(self):
        b = Budget(max_cost_usd=1.0)
        self.assertIsNone(b.exceeded())
        b.record(Usage(cost_usd=1.5), "any")
        reason = b.exceeded()
        self.assertIsNotNone(reason)
        self.assertIn("cost ceiling", reason)

    def test_token_ceiling(self):
        b = Budget(max_tokens=100)
        b.record(Usage(input_tokens=60, output_tokens=60))
        self.assertIn("token budget", b.exceeded())

    def test_record_prices_when_unknown(self):
        b = Budget()
        b.record(Usage(input_tokens=1000, output_tokens=1000), "claude-sonnet-4-5")
        self.assertGreater(b.usage.cost_usd, 0)


if __name__ == "__main__":
    unittest.main()
