"""Transport tests: retry with jitter, transient bodies, stream resilience."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from orca.providers.transport import (RetryPolicy, StreamInterrupted,
                                      Transport, TransportError,
                                      parse_sse_line)


def sse(*events):
    lines = []
    for e in events:
        if e is None:
            lines.append(b"data: [DONE]\n\n")
        else:
            lines.append(f"data: {json.dumps(e)}\n\n".encode())
    return io.BytesIO(b"".join(lines))


class TestSSEParsing(unittest.TestCase):
    def test_data_line_parses(self):
        self.assertEqual(parse_sse_line('data: {"a": 1}'), {"a": 1})

    def test_done_and_noise_are_ignored(self):
        self.assertIsNone(parse_sse_line("data: [DONE]"))
        self.assertIsNone(parse_sse_line("event: ping"))
        self.assertIsNone(parse_sse_line("garbage-not-json"))

    def test_bad_json_is_skipped_not_fatal(self):
        self.assertIsNone(parse_sse_line("data: {broken"))


class TestRetryPolicy(unittest.TestCase):
    def test_backoff_is_capped_and_jittered(self):
        policy = RetryPolicy()
        for attempt in range(6):
            d = policy.delay(attempt)
            base = min(8.0, 2.0 ** attempt)
            self.assertGreaterEqual(d, base)
            self.assertLessEqual(d, base + policy.jitter)

    def test_single_attempt_policy_never_retries(self):
        self.assertEqual(RetryPolicy(attempts=1).attempts, 1)


class TestTransportRetries(unittest.TestCase):
    def test_429_retried_then_succeeds(self):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=120):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise urllib.error.HTTPError(
                    str(req.full_url), 429, "Too Many Requests",
                    {}, io.BytesIO(b"rate limited"))
            return sse({"choices": [{"delta": {"content": "ok"}}]}, None)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch("time.sleep"):
            out = list(Transport().post("http://x", {}, {"m": 1}))
        self.assertEqual(calls["n"], 3)
        self.assertEqual(out, [{"choices": [{"delta": {"content": "ok"}}]}])

    def test_gateway_io_timeout_400_is_retried(self):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=120):
            calls["n"] += 1
            if calls["n"] == 1:
                raise urllib.error.HTTPError(
                    str(req.full_url), 400, "Bad Request",
                    {}, io.BytesIO(b"upstream read failed: i/o timeout"))
            return sse({"choices": [{"delta": {}}]}, None)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch("time.sleep"):
            list(Transport().post("http://x", {}, {"m": 1}))
        self.assertEqual(calls["n"], 2)

    def test_non_json_error_body_surfaces(self):
        def fake_urlopen(req, timeout=120):
            raise urllib.error.HTTPError(
                str(req.full_url), 401, "Unauthorized",
                {}, io.BytesIO(b"invalid api token"))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(TransportError) as ctx:
                list(Transport().post("http://x", {}, {"m": 1}))
        self.assertIn("invalid api token", str(ctx.exception))
        self.assertEqual(ctx.exception.status, 401)

    def test_connection_errors_exhaust_retries(self):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=120):
            calls["n"] += 1
            raise urllib.error.URLError("connection refused")
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch("time.sleep"):
            with self.assertRaises(TransportError):
                list(Transport().post("http://x", {}, {"m": 1}))
        self.assertEqual(calls["n"], 3)


class TestStreamResilience(unittest.TestCase):
    def test_stream_dying_empty_retries_whole_request(self):
        calls = {"n": 0}

        class DyingEmpty(io.BytesIO):
            def __iter__(self):
                raise OSError("connection reset")
                yield  # pragma: no cover

        def fake_urlopen(req, timeout=120):
            calls["n"] += 1
            if calls["n"] == 1:
                return DyingEmpty()
            return sse({"choices": [{"delta": {"content": "fine"}}]}, None)

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch("time.sleep"):
            out = list(Transport().post("http://x", {}, {"m": 1}))
        self.assertEqual(calls["n"], 2)
        self.assertEqual(out[0]["choices"][0]["delta"]["content"], "fine")

    def test_stream_dying_mid_content_keeps_partial(self):
        calls = {"n": 0}

        class DyingMid:
            def __iter__(self):
                yield b'data: {"choices": [{"delta": {"content": "half"}}]}\n\n'
                raise OSError("stream cut")

        def fake_urlopen(req, timeout=120):
            calls["n"] += 1
            return DyingMid()

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch("time.sleep"):
            with self.assertRaises(StreamInterrupted) as ctx:
                list(Transport().post("http://x", {}, {"m": 1}))
        self.assertEqual(calls["n"], 1)  # no pointless retry: content flowed
        self.assertEqual(ctx.exception.partial[0]["choices"][0]["delta"]
                         ["content"], "half")


if __name__ == "__main__":
    unittest.main()
