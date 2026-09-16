import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orca.config import PROVIDER_PRESETS
from orca.providers import (AnthropicProvider, OpenAICompatProvider, MockProvider,
                            list_remote_models,
                            ProviderError, Transport, to_openai_messages)


class FakeTransport(Transport):
    """Replays scripted SSE payloads; records requests (deep-copied)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __init__(self, responses):
        super().__init__()
        self.responses = list(responses)
        self.requests = []
        self.gets = []

    def get(self, url, headers, timeout=20):
        self.gets.append({"url": url, "headers": headers})
        body = self.responses.pop(0)
        if isinstance(body, Exception):
            raise body
        return body

    def post(self, url, headers, payload, timeout=600):
        self.requests.append({"url": url, "headers": headers,
                              "payload": json.loads(json.dumps(payload))})
        if not self.responses:
            raise ProviderError("no more scripted responses")
        for chunk in self.responses.pop(0):
            yield chunk


def sse(event: dict) -> str:
    return json.dumps(event)


CONF_OPENAI = {"name": "openai", "kind": "openai",
               "base_url": "https://api.example.com/v1", "api_key": "sk-test", "headers": {}}
CONF_ANTHROPIC = {"name": "anthropic", "kind": "anthropic",
                  "base_url": "https://api.example.com", "api_key": "sk-test", "headers": {}}


def collect(events):
    out = {"text": "", "tools": [], "usage": None, "stop": None, "message": None}
    for kind, payload in events:
        if kind == "text":
            out["text"] += payload
        elif kind == "tool_use":
            out["tools"].append(payload)
        elif kind == "usage":
            out["usage"] = payload
        elif kind == "stop":
            out["stop"] = payload
        elif kind == "message":
            out["message"] = payload
    return out


class TestOpenAIStream(unittest.TestCase):
    def test_text_and_tool_call(self):
        chunks = [
            sse({"choices": [{"delta": {"content": "Hello "}}]}),
            sse({"choices": [{"delta": {"content": "world"}}]}),
            sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_1", "function": {"name": "bash", "arguments": "{\"comm"}}]}}]}),
            sse({"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "and\":\"ls\"}"}}]}}]}),
            sse({"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}),
            sse({"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": 7}}),
            "[DONE]",
        ]
        provider = OpenAICompatProvider(CONF_OPENAI, "gpt-5.1", transport=FakeTransport([chunks]))
        result = collect(provider.stream("sys", [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]))
        self.assertEqual(result["text"], "Hello world")
        self.assertEqual(len(result["tools"]), 1)
        self.assertEqual(result["tools"][0]["name"], "bash")
        self.assertEqual(result["tools"][0]["input"], {"command": "ls"})
        self.assertEqual(result["usage"]["input"], 100)
        self.assertEqual(result["stop"], "tool_calls")
        msg = result["message"]
        self.assertEqual(msg["role"], "assistant")
        self.assertEqual(msg["content"][0]["type"], "text")
        self.assertEqual(msg["content"][1]["type"], "tool_use")

    def test_stream_options_fallback(self):
        chunks_bad = [json.dumps({"error": {"message": "stream_options is not supported"}})]
        chunks_good = [
            sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}),
            "[DONE]",
        ]
        transport = FakeTransport([chunks_bad, chunks_good])
        provider = OpenAICompatProvider(
            dict(CONF_OPENAI, name="custom", base_url="http://localhost:9999/v1"),
            "m", transport=transport)
        # custom providers don't send stream_options at all; craft one that does
        provider2 = OpenAICompatProvider(CONF_OPENAI, "m", transport=transport)
        result = collect(provider2.stream("s", [{"role": "user", "content": [{"type": "text", "text": "x"}]}]))
        self.assertEqual(result["text"], "ok")
        # the first attempt included stream_options, the retry must not
        self.assertIn("stream_options", transport.requests[0]["payload"])
        self.assertNotIn("stream_options", transport.requests[1]["payload"])

    def test_error_event(self):
        chunks = [sse({"error": {"message": "boom"}})]
        provider = OpenAICompatProvider(CONF_OPENAI, "m", transport=FakeTransport([chunks]))
        with self.assertRaises(ProviderError):
            list(provider.stream("s", [{"role": "user", "content": [{"type": "text", "text": "x"}]}]))


class TestAnthropicStream(unittest.TestCase):
    def test_text_and_tool_use(self):
        chunks = [
            sse({"type": "message_start", "message": {"usage": {"input_tokens": 42}}}),
            sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
            sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}}),
            sse({"type": "content_block_stop", "index": 0}),
            sse({"type": "content_block_start", "index": 1,
                 "content_block": {"type": "tool_use", "id": "tu_1", "name": "read_file"}}),
            sse({"type": "content_block_delta", "index": 1,
                 "delta": {"type": "input_json_delta", "partial_json": '{"path": "x.py"'}}),
            sse({"type": "content_block_delta", "index": 1,
                 "delta": {"type": "input_json_delta", "partial_json": ", \"limit\": 5}"}}),
            sse({"type": "content_block_stop", "index": 1}),
            sse({"type": "message_delta", "delta": {"stop_reason": "tool_use"},
                 "usage": {"output_tokens": 12}}),
            sse({"type": "message_stop"}),
        ]
        provider = AnthropicProvider(CONF_ANTHROPIC, "claude-sonnet-4-5", transport=FakeTransport([chunks]))
        result = collect(provider.stream("sys", [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]))
        self.assertEqual(result["text"], "Hi")
        self.assertEqual(result["tools"][0]["id"], "tu_1")
        self.assertEqual(result["tools"][0]["input"], {"path": "x.py", "limit": 5})
        self.assertEqual(result["usage"]["input"], 42)
        self.assertEqual(result["usage"]["output"], 12)
        self.assertEqual(result["stop"], "tool_use")

    def test_first_message_must_be_user(self):
        provider = AnthropicProvider(CONF_ANTHROPIC, "m")
        msgs = [
            {"role": "assistant", "content": [{"type": "text", "text": "orphan"}]},
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        ]
        converted = provider._to_anthropic(msgs)
        self.assertEqual(len(converted), 1)
        self.assertEqual(converted[0]["role"], "user")


class TestConversions(unittest.TestCase):
    def test_to_openai_roundtrip(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "fix it"}]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "on it"},
                {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "ls"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "file a\nfile b"},
            ]},
        ]
        out = to_openai_messages("SYS", messages)
        self.assertEqual(out[0], {"role": "system", "content": "SYS"})
        self.assertEqual(out[1], {"role": "user", "content": "fix it"})
        assistant = out[2]
        self.assertEqual(assistant["role"], "assistant")
        self.assertEqual(assistant["content"], "on it")
        self.assertEqual(assistant["tool_calls"][0]["function"]["name"], "bash")
        self.assertEqual(json.loads(assistant["tool_calls"][0]["function"]["arguments"]),
                         {"command": "ls"})
        tool = out[3]
        self.assertEqual(tool["role"], "tool")
        self.assertEqual(tool["tool_call_id"], "t1")


class TestMock(unittest.TestCase):
    def test_script(self):
        provider = MockProvider(script=[
            {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "ls",
                                               "input": {}}]},
            {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
        ])
        msgs = [{"role": "user", "content": [{"type": "text", "text": "go"}]}]
        first = collect(provider.stream("s", msgs))
        self.assertEqual(first["tools"][0]["name"], "ls")
        second = collect(provider.stream("s", msgs))
        self.assertEqual(second["text"], "done")
        third = collect(provider.stream("s", msgs))
        self.assertIn("script exhausted", third["text"])


if __name__ == "__main__":
    unittest.main()


class TestAnthropicPromptCaching(unittest.TestCase):
    TOOLS = [{"name": "read_file", "description": "Read a file",
              "input_schema": {"type": "object", "properties": {}, "required": []}}]

    def _payload_for(self, system, tools, prompt_caching=True):
        chunks = [
            sse({"type": "message_start", "message": {"usage": {"input_tokens": 10}}}),
            sse({"type": "content_block_start", "index": 0,
                 "content_block": {"type": "text", "text": ""}}),
            sse({"type": "content_block_delta", "index": 0,
                 "delta": {"type": "text_delta", "text": "ok"}}),
            sse({"type": "content_block_stop", "index": 0}),
            sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                 "usage": {"output_tokens": 2}}),
            sse({"type": "message_stop"}),
        ]
        provider = AnthropicProvider(CONF_ANTHROPIC, "claude-sonnet-4-5",
                                     transport=FakeTransport([chunks]),
                                     prompt_caching=prompt_caching)
        list(provider.stream(system, [{"role": "user",
                                       "content": [{"type": "text", "text": "hi"}]}],
                             tools=tools))
        return provider.transport.requests[0]["payload"]

    def test_short_prefix_not_cached(self):
        payload = self._payload_for("You are Orca.", self.TOOLS)
        self.assertEqual(payload["system"], "You are Orca.")
        self.assertNotIn("cache_control", json.dumps(payload))

    def test_long_prefix_cached(self):
        big_system = "You are Orca. " + "guidance " * 600   # ~5000 chars > 1200 tokens
        payload = self._payload_for(big_system, self.TOOLS)
        self.assertIsInstance(payload["system"], list)
        self.assertEqual(payload["system"][0]["type"], "text")
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})
        tools = payload["tools"]
        self.assertEqual(tools[-1]["cache_control"], {"type": "ephemeral"})

    def test_caching_disabled(self):
        big_system = "You are Orca. " + "guidance " * 600
        payload = self._payload_for(big_system, self.TOOLS, prompt_caching=False)
        self.assertEqual(payload["system"], big_system)
        self.assertNotIn("cache_control", json.dumps(payload))


class TestAnthropicUsageTotals(unittest.TestCase):
    """Anthropic's input_tokens excludes cache; Orca's contract says input =
    everything processed (cache included) so pricing never goes negative."""

    def test_cache_tokens_folded_into_input(self):
        chunks = [
            sse({"type": "message_start", "message": {"usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 5000,
                "cache_creation_input_tokens": 4900}}}),
            sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                 "usage": {"output_tokens": 2}}),
            sse({"type": "message_stop"}),
        ]
        provider = AnthropicProvider(CONF_ANTHROPIC, "claude-sonnet-4-5",
                                     transport=FakeTransport([chunks]))
        events = list(provider.stream("s", [{"role": "user",
                                             "content": [{"type": "text", "text": "hi"}]}]))
        usage = next(dict(p) for k, p in events if k == "usage")
        self.assertEqual(usage["input"], 10 + 5000 + 4900)
        self.assertEqual(usage["cache_read"], 5000)
        self.assertEqual(usage["cache_write"], 4900)


class TestReasoningStreams(unittest.TestCase):
    """Thinking models (DeepSeek-R1, Kimi, GLM, Qwen) split reasoning from
    content. Orca shows reasoning live but never persists it to the transcript."""

    def test_openai_reasoning_content_streamed_not_stored(self):
        chunks = [
            sse({"choices": [{"delta": {"reasoning_content": "let me think…"}}]}),
            sse({"choices": [{"delta": {"reasoning_content": " done thinking."}}]}),
            sse({"choices": [{"delta": {"content": "The answer is 42."}}]}),
            sse({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            sse({"usage": {"prompt_tokens": 10, "completion_tokens": 5}}),
        ]
        provider = OpenAICompatProvider(CONF_OPENAI, "deepseek-reasoner",
                                        transport=FakeTransport([chunks]))
        events = list(provider.stream("s", [{"role": "user",
                                             "content": [{"type": "text", "text": "q"}]}]))
        reasoning = "".join(p for k, p in events if k == "reasoning")
        self.assertEqual(reasoning, "let me think… done thinking.")
        text = "".join(p for k, p in events if k == "text")
        self.assertEqual(text, "The answer is 42.")
        message = next(p for k, p in events if k == "message")
        stored = "".join(b.get("text", "") for b in message["content"]
                         if b.get("type") == "text")
        self.assertEqual(stored, "The answer is 42.")   # reasoning NOT persisted

    def test_anthropic_thinking_block(self):
        chunks = [
            sse({"type": "message_start", "message": {"usage": {"input_tokens": 5}}}),
            sse({"type": "content_block_start", "index": 0,
                 "content_block": {"type": "thinking", "thinking": ""}}),
            sse({"type": "content_block_delta", "index": 0,
                 "delta": {"type": "thinking_delta", "thinking": "hmm…"}}),
            sse({"type": "content_block_stop", "index": 0}),
            sse({"type": "content_block_start", "index": 1,
                 "content_block": {"type": "text", "text": ""}}),
            sse({"type": "content_block_delta", "index": 1,
                 "delta": {"type": "text_delta", "text": "Answer."}}),
            sse({"type": "content_block_stop", "index": 1}),
            sse({"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                 "usage": {"output_tokens": 3}}),
            sse({"type": "message_stop"}),
        ]
        provider = AnthropicProvider(CONF_ANTHROPIC, "claude-sonnet-4-5",
                                     transport=FakeTransport([chunks]))
        events = list(provider.stream("s", [{"role": "user",
                                             "content": [{"type": "text", "text": "q"}]}]))
        self.assertIn("reasoning", [k for k, _ in events])
        message = next(p for k, p in events if k == "message")
        types = [b.get("type") for b in message["content"]]
        self.assertIn("text", types)
        self.assertNotIn("thinking", types)


class TestListRemoteModels(unittest.TestCase):
    def test_openai_style_models_endpoint(self):
        transport = FakeTransport([json.dumps(
            {"data": [{"id": "model-b"}, {"id": "model-a"}, {"id": "model-c"}]})])
        provider = OpenAICompatProvider(CONF_OPENAI, "m", transport=transport)
        models = list_remote_models(provider)
        self.assertEqual(models, ["model-a", "model-b", "model-c"])
        self.assertIn("/models", transport.gets[0]["url"])
        self.assertEqual(transport.gets[0]["headers"]["Authorization"], "Bearer sk-test")

    def test_anthropic_style_models_endpoint(self):
        transport = FakeTransport([json.dumps(
            {"data": [{"id": "claude-sonnet-4-5"}, {"id": "claude-haiku-4-5"}]})])
        provider = AnthropicProvider(CONF_ANTHROPIC, "claude-sonnet-4-5",
                                     transport=transport)
        models = list_remote_models(provider)
        self.assertEqual(models, ["claude-haiku-4-5", "claude-sonnet-4-5"])

    def test_error_propagates(self):
        from orca.providers import ProviderError as PE
        transport = FakeTransport([PE("HTTP 500: boom")])
        provider = OpenAICompatProvider(CONF_OPENAI, "m", transport=transport)
        with self.assertRaises(PE):
            list_remote_models(provider)


class TestProviderCoverage(unittest.TestCase):
    """The 'bring your own API' promise: every major AI company, one preset."""

    EXPECTED = {
        "google": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
        "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
        "moonshot": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
        "zai": ("https://api.z.ai/api/paas/v4", "ZAI_API_KEY"),
        "minimax": ("https://api.minimax.io/v1", "MINIMAX_API_KEY"),
        "dashscope": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
        "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
        "fireworks": ("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
        "perplexity": ("https://api.perplexity.ai", "PERPLEXITY_API_KEY"),
        "cohere": ("https://api.cohere.ai/compatibility/v1", "COHERE_API_KEY"),
        "deepinfra": ("https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY"),
        "sambanova": ("https://api.sambanova.ai/v1", "SAMBANOVA_API_KEY"),
        "nebius": ("https://api.studio.nebius.ai/v1", "NEBIUS_API_KEY"),
        "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
        "huggingface": ("https://router.huggingface.co/v1", "HF_TOKEN"),
        "github": ("https://models.github.ai/inference", "GITHUB_TOKEN"),
        "dahl": ("https://inference.dahl.global/v1", "DAHL_API_KEY"),
        "anthropic": ("https://api.anthropic.com", "ANTHROPIC_API_KEY"),
        "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
        "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
        "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
        "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
        "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
        "together": ("https://api.together.ai/v1", "TOGETHER_API_KEY"),
        "ollama": ("http://localhost:11434/v1", None),
    }

    def test_all_presets_present_and_correct(self):
        for name, (url, env) in self.EXPECTED.items():
            preset = PROVIDER_PRESETS.get(name)
            self.assertIsNotNone(preset, f"missing provider: {name}")
            self.assertEqual(preset["base_url"], url, name)
            self.assertEqual(preset["key_env"], env, name)

    def test_at_least_30_providers(self):
        self.assertGreaterEqual(len(PROVIDER_PRESETS), 30)


class TestThinkSplitter(unittest.TestCase):
    """Inline <think>...</think> reasoning routed to the reasoning lane."""

    def _run(self, chunks):
        from orca.providers import _ThinkSplitter
        sp = _ThinkSplitter()
        out = []
        for c in chunks:
            out.extend(sp.feed(c))
        out.extend(sp.flush())
        return out

    def test_no_tags_passthrough(self):
        out = self._run(["just ", "normal text"])
        self.assertEqual(out, [("text", "just "), ("text", "normal text")])

    def test_think_block_routed_to_reasoning(self):
        out = self._run(["<think>plan it</think>OK"])
        self.assertEqual(out, [("reasoning", "plan it"), ("text", "OK")])

    def test_tag_split_across_chunks(self):
        out = self._run(["<thi", "nk>abc</th", "ink>done"])
        self.assertEqual(out, [("reasoning", "abc"), ("text", "done")])

    def test_multiple_think_blocks(self):
        out = self._run(["<think>a</think>1<think>b</think>2"])
        self.assertEqual(out, [("reasoning", "a"), ("text", "1"),
                               ("reasoning", "b"), ("text", "2")])

    def test_unterminated_think_is_reasoning(self):
        out = self._run(["<think>half way"])
        self.assertEqual(out, [("reasoning", "half way")])

    def test_literal_partial_tail_flushed_as_text(self):
        # "<thi" that never completes is plain text, not lost
        out = self._run(["wait <thi"])
        self.assertEqual(out, [("text", "wait "), ("text", "<thi")])

    def test_stream_end_to_end_think_stripped_from_message(self):
        conf = {"name": "x", "kind": "openai", "base_url": "http://x",
                "api_key": "k"}
        sse = [
            '{"choices":[{"delta":{"content":"<think>reason here</t"}}]}',
            '{"choices":[{"delta":{"content":"hink>\\nAnswer: 42"}}]}',
        ]
        tr = FakeTransport([sse])
        p = OpenAICompatProvider(conf, "m", transport=tr)
        events = []
        msg = None
        for kind, payload in p.stream("sys", [{"role": "user", "content": [
                {"type": "text", "text": "q"}]}]):
            events.append((kind, payload))
            if kind == "message":
                msg = payload
        self.assertIn(("text", "\nAnswer: 42"), events)
        self.assertIn(("reasoning", "reason here"), events)
        stored = "".join(b.get("text", "") for b in msg["content"])
        self.assertEqual(stored.strip(), "Answer: 42")
        self.assertNotIn("think", stored)

    def test_minimax_tool_call_block_dropped(self):
        out = self._run(["before", "<minimax:tool_call>{\"name\":\"x\"}",
                         "</minimax:tool_call>", "after"])
        self.assertEqual([k for k, _ in out], ["text", "text"])
        self.assertEqual("".join(v for _, v in out), "beforeafter")

    def test_orphan_close_tag_stripped(self):
        out = self._run(["4</minimax:tool_call>"])
        self.assertEqual(out, [("text", "4")])
        out = self._run(["done</think>"])
        self.assertEqual(out, [("text", "done")])

    def test_mm_tag_split_across_chunks(self):
        out = self._run(["ok<mini", "max:tool_call>hidden",
                         "</minimax:tool_", "call>end"])
        self.assertEqual("".join(v for k, v in out if k == "text"), "okend")

    def test_reasoning_deltas_strip_tag_noise(self):
        conf = {"name": "x", "kind": "openai", "base_url": "http://x",
                "api_key": "k"}
        sse = [
            '{"choices":[{"delta":{"reasoning_content":"<think>step one\\n"}}]}',
            '{"choices":[{"delta":{"reasoning_content":"step two</think>"}}]}',
            '{"choices":[{"delta":{"content":"Answer."}}]}',
        ]
        tr = FakeTransport([sse])
        p = OpenAICompatProvider(conf, "m", transport=tr)
        events = [e for e in p.stream("s", [{"role": "user", "content": [
            {"type": "text", "text": "q"}]}])]
        reasoning = "".join(v for k, v in events if k == "reasoning")
        self.assertEqual(reasoning, "step one\nstep two")
        self.assertNotIn("<think>", reasoning)
