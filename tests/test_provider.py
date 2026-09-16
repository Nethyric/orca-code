"""Provider adapter tests: wire format, stream parsing, construction."""
import io
import json
import unittest

from orca.providers.catalog import CATALOG, default_model, expand_alias
from orca.providers.provider import (OpenAICompatProvider, ProviderError,
                                     Reply, make_provider, to_wire)
from orca.providers.transport import Transport
from orca.runtime.config import Config

from tests.helpers import tmp_root


class FakeTransport:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def post(self, url, headers, payload):
        self.calls.append({"url": url, "headers": headers,
                           "payload": payload})
        for event in self.events:
            yield event


def ev(delta=None, finish=None, usage=None):
    out = {"choices": [{"delta": delta or {}}]}
    if finish:
        out["choices"][0]["finish_reason"] = finish
    if usage is not None:
        out["usage"] = usage
        out["choices"] = []
    return out


class TestToWire(unittest.TestCase):
    def test_system_user_and_text(self):
        wire = to_wire([{"role": "user",
                         "content": [{"type": "text", "text": "hi"}]}],
                       "be helpful")
        self.assertEqual(wire[0], {"role": "system", "content": "be helpful"})
        self.assertEqual(wire[1], {"role": "user", "content": "hi"})

    def test_tool_use_becomes_tool_calls(self):
        wire = to_wire([{"role": "assistant", "content": [
            {"type": "text", "text": "working"},
            {"type": "tool_use", "id": "c1", "name": "bash",
             "input": {"command": "ls"}}]}], "")
        entry = wire[0]
        self.assertEqual(entry["role"], "assistant")
        self.assertEqual(entry["content"], "working")
        self.assertEqual(entry["tool_calls"][0]["function"]["name"], "bash")
        self.assertEqual(
            json.loads(entry["tool_calls"][0]["function"]["arguments"]),
            {"command": "ls"})

    def test_tool_results_become_tool_messages(self):
        wire = to_wire([{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1",
             "content": "file contents"}]}], "")
        self.assertEqual(wire[0]["role"], "tool")
        self.assertEqual(wire[0]["tool_call_id"], "c1")
        self.assertEqual(wire[0]["content"], "file contents")


class TestStreamParsing(unittest.TestCase):
    def make_provider(self, events, model="test-model"):
        from orca.providers.catalog import ProviderSpec
        spec = ProviderSpec(name="custom", kind="openai",
                            base_url="http://x/v1")
        fake = FakeTransport(events)
        provider = OpenAICompatProvider(spec, model, "k", transport=fake)
        return provider, fake

    def test_text_thinking_and_usage(self):
        provider, fake = self.make_provider([
            ev(delta={"reasoning_content": "thinking hard"}),
            ev(delta={"content": "hel"}),
            ev(delta={"content": "lo"}),
            ev(finish="stop"),
            ev(usage={"prompt_tokens": 100, "completion_tokens": 20,
                      "prompt_tokens_details": {"cached_tokens": 80}}),
        ])
        reply = provider.reply([], None, system="s")
        self.assertEqual(reply.text, "hello")
        self.assertEqual(reply.thinking, "thinking hard")
        self.assertEqual(reply.stop_reason, "stop")
        self.assertEqual(reply.usage.input_tokens, 100)
        self.assertEqual(reply.usage.output_tokens, 20)
        self.assertEqual(reply.usage.cache_read, 80)

    def test_fragmented_tool_calls_assemble(self):
        provider, _ = self.make_provider([
            ev(delta={"tool_calls": [{"index": 0, "id": "c1",
                                      "function": {"name": "ba"}}]}),
            ev(delta={"tool_calls": [{"index": 0,
                                      "function": {"name": "sh",
                                                   "arguments": '{"comm'}}]}),
            ev(delta={"tool_calls": [{"index": 0,
                                      "function": {"arguments": 'and":"ls"}'}}]}),
            ev(finish="tool_calls"),
        ])
        reply = provider.reply([], None)
        self.assertEqual(len(reply.tool_calls), 1)
        call = reply.tool_calls[0]
        self.assertEqual(call["id"], "c1")
        self.assertEqual(call["name"], "bash")
        self.assertEqual(call["input"], {"command": "ls"})

    def test_payload_shape(self):
        provider, fake = self.make_provider([])
        provider.reply([{"role": "user",
                         "content": [{"type": "text", "text": "hi"}]}],
                       [{"name": "bash", "description": "d",
                         "parameters": {"type": "object",
                                        "properties": {}}}], system="sys")
        payload = fake.calls[0]["payload"]
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["tools"][0]["type"], "function")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("/chat/completions", fake.calls[0]["url"])
        self.assertEqual(fake.calls[0]["headers"]["Authorization"],
                         "Bearer k")

    def test_bad_tool_arguments_do_not_crash(self):
        provider, _ = self.make_provider([
            ev(delta={"tool_calls": [{"index": 0, "id": "c1",
                                      "function": {
                                          "name": "bash",
                                          "arguments": "{not json"}}]}),
            ev(finish="tool_calls"),
        ])
        reply = provider.reply([], None)
        self.assertIn("_raw", reply.tool_calls[0]["input"])


class TestCatalog(unittest.TestCase):
    def test_thirty_one_providers(self):
        self.assertEqual(len(CATALOG), 31)
        for must in ("anthropic", "openai", "openrouter", "ollama",
                     "lmstudio", "custom", "mock", "dahl"):
            self.assertIn(must, CATALOG)

    def test_local_providers_need_no_key(self):
        self.assertTrue(CATALOG["ollama"].local)
        self.assertTrue(CATALOG["lmstudio"].local)
        self.assertIsNone(CATALOG["ollama"].key_env)

    def test_alias_expansion(self):
        self.assertEqual(expand_alias("kimi"), "moonshotai/Kimi-K2.6")
        self.assertEqual(expand_alias("GPT-5.1"), "GPT-5.1")  # untouched

    def test_default_models_exist(self):
        self.assertTrue(default_model("anthropic"))
        self.assertEqual(default_model("custom"), "")


class TestMakeProvider(unittest.TestCase):
    def make_cfg(self, **over):
        cfg = Config(root=tmp_root(), home=tmp_root())
        for key, value in over.items():
            cfg.set(key, value)
        return cfg

    def test_mock_provider(self):
        cfg = self.make_cfg(provider="mock")
        provider = make_provider(cfg)
        self.assertEqual(provider.name, "mock")

    def test_missing_key_gives_guidance(self):
        cfg = self.make_cfg(provider="deepseek")
        with self.assertRaises(ProviderError) as ctx:
            make_provider(cfg)
        self.assertIn("DEEPSEEK_API_KEY", str(ctx.exception))

    def test_local_provider_works_without_key(self):
        cfg = self.make_cfg(provider="ollama", model="llama3.3")
        provider = make_provider(cfg)
        self.assertEqual(provider.model, "llama3.3")
        self.assertIn("localhost:11434", provider.spec.base_url)

    def test_stored_key_is_used(self):
        cfg = self.make_cfg(provider="openai", model="gpt-5.1")
        cfg.set("api_keys", {"openai": "sk-test"})
        provider = make_provider(cfg)
        self.assertEqual(provider.api_key, "sk-test")

    def test_custom_base_url_override(self):
        cfg = self.make_cfg(provider="custom", model="m")
        cfg.set("base_urls", {"custom": "http://gateway.local/v1"})
        cfg.set("api_keys", {"custom": "k"})
        provider = make_provider(cfg)
        self.assertEqual(provider.spec.base_url, "http://gateway.local/v1")

    def test_unknown_provider_named_in_error(self):
        cfg = self.make_cfg(provider="nope")
        with self.assertRaises(ProviderError) as ctx:
            make_provider(cfg)
        self.assertIn("nope", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
