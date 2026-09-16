"""Streaming LLM providers for Orca Code.

Two wire formats are supported:
  * "anthropic"  — the Anthropic Messages API (native tool use, SSE)
  * "openai"     — the OpenAI Chat Completions API (SSE), which is also
                   spoken by OpenRouter, Groq, DeepSeek, Mistral, Together,
                   Ollama, LM Studio and countless gateways.

Everything uses only the standard library (urllib + json), with retries,
backoff and a transport seam that makes the whole stack unit-testable.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .config import Config

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class ProviderError(Exception):
    """Raised for any provider failure after retries are exhausted."""


# --------------------------------------------------------------------------
# Transport (overridable for tests)
# --------------------------------------------------------------------------

class Transport:
    """POSTs a JSON payload and yields SSE ``data:`` strings."""

    def get(self, url: str, headers: Dict[str, str], timeout: int = 20) -> str:
        """GET a plain (JSON) body — used for the /models listing."""
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"HTTP {exc.code}: {exc.reason}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise ProviderError(f"Cannot reach {url}: {exc}") from exc

    def post(self, url: str, headers: Dict[str, str], payload: Dict[str, Any],
             timeout: int = 600) -> Iterator[str]:
        body = json.dumps(payload).encode("utf-8")
        attempt = 0
        while True:
            attempt += 1
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as exc:
                detail = self._error_detail(exc)
                if exc.code in RETRYABLE_STATUS and attempt <= 3:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                if attempt <= 3:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"Cannot reach {url}: {exc}") from exc
            try:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").rstrip("\r\n")
                    if not line or line.startswith(":") or line.startswith("event:"):
                        continue
                    if line.startswith("data:"):
                        yield line[5:].strip()
            except (urllib.error.URLError, OSError) as exc:  # mid-stream failure
                raise ProviderError(f"Connection lost mid-stream: {exc}") from exc
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            return

    @staticmethod
    def _error_detail(exc: urllib.error.HTTPError) -> str:
        try:
            raw = exc.read().decode("utf-8", "replace")
            data = json.loads(raw)
            err = data.get("error", data)
            if isinstance(err, dict):
                return str(err.get("message") or raw)
            return str(err or raw)
        except Exception:
            return str(exc.reason)


# --------------------------------------------------------------------------
# Message format helpers (internal canonical format ~ Anthropic-shaped)
#   user:      {"role":"user", "content":[text|tool_result blocks]}
#   assistant: {"role":"assistant", "content":[text|tool_use blocks]}
# --------------------------------------------------------------------------

def text_block(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def tool_use_block(id: str, name: str, input: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "tool_use", "id": id, "name": name, "input": input}


def tool_result_block(tool_use_id: str, content: str, is_error: bool = False) -> Dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": tool_use_id,
            "content": content, "is_error": is_error}


def to_openai_messages(system: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in messages:
        if msg.get("role") == "assistant":
            text = "".join(b.get("text", "") for b in msg["content"] if b.get("type") == "text")
            calls = [
                {
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})},
                }
                for b in msg["content"] if b.get("type") == "tool_use"
            ]
            entry: Dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
        else:
            texts: List[str] = []
            for block in msg["content"]:
                if block.get("type") == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": block.get("content", ""),
                    })
                elif block.get("type") == "text" and block.get("text", "").strip():
                    texts.append(block["text"])
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
    return [m for m in out if m.get("role") == "system" or m.get("content") is not None
            or m.get("tool_calls")]


def openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t.get("description", ""),
                      "parameters": t.get("input_schema", {"type": "object", "properties": {}})}}
        for t in tools
    ]


def anthropic_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"name": t["name"], "description": t.get("description", ""),
             "input_schema": t.get("input_schema", {"type": "object", "properties": {}})}
            for t in tools]


# --------------------------------------------------------------------------
# Base provider
# --------------------------------------------------------------------------

class BaseProvider:
    name = "base"
    kind = "openai"

    def __init__(self, conf: Dict[str, Any], model: str, transport: Optional[Transport] = None,
                 max_tokens: Optional[int] = None):
        self.conf = conf
        self.model = model
        self.transport = transport or Transport()
        self.max_tokens = max_tokens

    @property
    def label(self) -> str:
        return f"{self.name}/{self.model}"

    # Subclasses implement stream(). It must yield events:
    #   ("text", str)                       — a text delta
    #   ("tool_use", {id,name,input})       — a completed tool call
    #   ("usage", {input, output, cache_read, cache_write})
    #   ("stop", reason)
    #   ("message", internal_assistant_msg) — final assembled message
    def stream(self, system: str, messages: List[Dict[str, Any]],
               tools: Optional[List[Dict[str, Any]]] = None
               ) -> Iterator[Tuple[str, Any]]:
        raise NotImplementedError


# some models sprinkle literal protocol tags into their reasoning stream
_TAG_NOISE = ("<think>", "</think>", "<minimax:tool_call>", "</minimax:tool_call>")


def _strip_tag_noise(text: str) -> str:
    for tag in _TAG_NOISE:
        if tag in text:
            text = text.replace(tag, "")
    return text


class _ThinkSplitter:
    """Routes inline markup in streamed content to the right lane.

    Some OpenAI-compatible providers (MiniMax, GLM, Qwen, DeepSeek-V style)
    return the model's chain-of-thought inside the content itself instead of
    a dedicated ``reasoning_content`` field, and occasionally leak native
    tool-protocol tags (``<minimax:tool_call>``) into plain text. This state
    machine splits the stream across chunk boundaries:

    - ``<think>...</think>``      -> ("reasoning", ...) — shown live, never stored
    - ``<minimax:tool_call>...``  -> dropped (protocol artifact, not user text)
    - everything else             -> ("text", ...) — stored in the message

    Orphan closing tags are removed silently.
    """

    OPEN_THINK = "<think>"
    CLOSE_THINK = "</think>"
    OPEN_MM = "<minimax:tool_call>"
    CLOSE_MM = "</minimax:tool_call>"

    def __init__(self) -> None:
        self.mode = "text"          # "text" | "think" | "drop"
        self.buf = ""

    def _candidates(self) -> List[str]:
        if self.mode == "think":
            return [self.CLOSE_THINK]
        if self.mode == "drop":
            return [self.CLOSE_MM]
        # text mode: openers transition; orphan closers are stripped in place
        return [self.OPEN_THINK, self.OPEN_MM, self.CLOSE_THINK, self.CLOSE_MM]

    def _emit(self, out: List[Tuple[str, str]], piece: str) -> None:
        if not piece:
            return
        if self.mode == "think":
            out.append(("reasoning", piece))
        elif self.mode == "text":
            out.append(("text", piece))
        # "drop": discard silently

    def feed(self, piece: str) -> List[Tuple[str, str]]:
        self.buf += piece
        out: List[Tuple[str, str]] = []
        while True:
            best_i, best_tag = -1, None
            for tag in self._candidates():
                i = self.buf.find(tag)
                if i != -1 and (best_i == -1 or i < best_i):
                    best_i, best_tag = i, tag
            if best_tag is not None:
                self._emit(out, self.buf[:best_i])
                self.buf = self.buf[best_i + len(best_tag):]
                if best_tag == self.OPEN_THINK:
                    self.mode = "think"
                elif best_tag == self.OPEN_MM:
                    self.mode = "drop"
                else:                       # any closing tag -> back to text
                    self.mode = "text"
                continue
            # hold back a tail that could be the start of any candidate tag
            # (e.g. "<thi" or "<mini" at the end of this chunk)
            keep = 0
            for tag in self._candidates():
                for k in range(min(len(tag) - 1, len(self.buf)), 0, -1):
                    if tag.startswith(self.buf[-k:]):
                        keep = max(keep, k)
                        break
            if keep:
                emit, self.buf = self.buf[:-keep], self.buf[-keep:]
            else:
                emit, self.buf = self.buf, ""
            self._emit(out, emit)
            return out

    def flush(self) -> List[Tuple[str, str]]:
        if not self.buf:
            return []
        out: List[Tuple[str, str]] = []
        self._emit(out, self.buf)   # leftover routed by mode (drop = discard)
        self.buf = ""
        return out


class OpenAICompatProvider(BaseProvider):
    kind = "openai"

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.conf.get("api_key"):
            headers["Authorization"] = f"Bearer {self.conf['api_key']}"
        headers.update(self.conf.get("headers") or {})
        return headers

    def stream(self, system, messages, tools=None):
        url = f"{self.conf['base_url']}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": to_openai_messages(system, messages),
            "stream": True,
        }
        if tools:
            payload["tools"] = openai_tools(tools)
        # default output budget: many OpenAI-compatible providers default to
        # a LOW cap (e.g. 4k), which silently truncates large single tool
        # calls (whole-file writes) mid-JSON — the call arrives unusable.
        out_cap = self.max_tokens or 32768
        # OpenAI's newer models only accept the new name.
        if self.conf.get("name") == "openai":
            payload["max_completion_tokens"] = out_cap
        else:
            payload["max_tokens"] = out_cap
        # include_usage is OpenAI-specific; some local servers reject it.
        include_usage = self.conf.get("name") not in ("ollama", "lmstudio", "custom")
        if include_usage:
            payload["stream_options"] = {"include_usage": True}

        started = False
        try:
            for event in self._stream_once(url, payload):
                started = True
                yield event
        except ProviderError as exc:
            if include_usage and not started and "stream_options" in str(exc):
                payload.pop("stream_options", None)
                yield from self._stream_once(url, payload)
            else:
                raise

    def _stream_once(self, url, payload) -> Iterator[Tuple[str, Any]]:
        text_parts: List[str] = []          # real text only (think stripped)
        tool_calls: Dict[int, Dict[str, Any]] = {}
        stop_reason: Optional[str] = None
        usage: Dict[str, int] = {}
        splitter = _ThinkSplitter()

        for data in self.transport.post(url, self._headers(), payload):
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            if chunk.get("error"):
                err = chunk["error"]
                raise ProviderError(str(err.get("message") or err))
            if chunk.get("usage"):
                u = chunk["usage"] or {}
                usage = {
                    "input": u.get("prompt_tokens", 0) or 0,
                    "output": u.get("completion_tokens", 0) or 0,
                    "cache_read": ((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)) or 0,
                    "cache_write": 0,
                }
            for choice in chunk.get("choices", []):
                delta = choice.get("delta") or {}
                # thinking models (DeepSeek-R1 style, Kimi, GLM, Qwen) stream
                # their reasoning separately — show it live but never persist it
                for rkey in ("reasoning_content", "reasoning"):
                    thought = delta.get(rkey)
                    if thought:
                        yield ("reasoning", _strip_tag_noise(thought))
                piece = delta.get("content")
                if piece:
                    for kind, chunk_out in splitter.feed(piece):
                        if kind == "reasoning":
                            yield ("reasoning", chunk_out)
                        else:
                            text_parts.append(chunk_out)
                            yield ("text", chunk_out)
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tool_calls.setdefault(idx, {"id": None, "name": "", "args": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["args"] += fn["arguments"]
                if choice.get("finish_reason"):
                    stop_reason = choice["finish_reason"]

        for kind, chunk_out in splitter.flush():
            if kind == "reasoning":
                yield ("reasoning", chunk_out)
            else:
                text_parts.append(chunk_out)
        content: List[Dict[str, Any]] = []
        joined = "".join(text_parts)
        if joined:
            content.append(text_block(joined))
        for idx in sorted(tool_calls):
            slot = tool_calls[idx]
            try:
                args = json.loads(slot["args"] or "{}")
            except ValueError:
                args = {"_raw": slot["args"]}
            content.append(tool_use_block(slot["id"] or f"call_{idx}", slot["name"], args))
            yield ("tool_use", {"id": slot["id"] or f"call_{idx}",
                                "name": slot["name"], "input": args})
        if not usage:
            usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        yield ("usage", usage)
        yield ("stop", stop_reason or ("tool_calls" if tool_calls else "end_turn"))
        yield ("message", {"role": "assistant", "content": content})


class AnthropicProvider(BaseProvider):
    kind = "anthropic"

    def __init__(self, conf: Dict[str, Any], model: str,
                 transport: Optional[Transport] = None, max_tokens: Optional[int] = None,
                 prompt_caching: bool = True):
        super().__init__(conf, model, transport, max_tokens)
        # Prompt caching gives ~90% discount on cached input tokens and kills
        # the "resume = full cache miss" cost penalty. Requires >= 1024
        # cacheable tokens, so we only opt in when the prefix is big enough.
        self.prompt_caching = prompt_caching

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.conf.get("api_key") or "",
            "anthropic-version": "2023-06-01",
        }
        headers.update(self.conf.get("headers") or {})
        return headers

    def stream(self, system, messages, tools=None):
        url = f"{self.conf['base_url']}/v1/messages"
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens or 16384,
            "messages": self._to_anthropic(messages),
            "stream": True,
        }
        cacheable_enough = (
            self.prompt_caching and tools
            and (len(system) + len(json.dumps(anthropic_tools(tools)))) / 3.8 >= 1200
        )
        if cacheable_enough:
            # cache the system prompt + tool definitions: stable across turns
            payload["system"] = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }]
            stamped = [dict(t) for t in anthropic_tools(tools)]
            stamped[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = stamped
        else:
            payload["system"] = system
            if tools:
                payload["tools"] = anthropic_tools(tools)

        blocks: Dict[int, Dict[str, Any]] = {}
        usage: Dict[str, int] = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        stop_reason = "end_turn"

        for data in self.transport.post(url, self._headers(), payload):
            try:
                event = json.loads(data)
            except ValueError:
                continue
            etype = event.get("type")
            if etype == "message_start":
                u = (event.get("message") or {}).get("usage") or {}
                # Anthropic reports input_tokens EXCLUDING cached tokens; the
                # UsageTracker contract (like OpenAI's prompt_tokens) is
                # "input = everything processed this turn", cache included —
                # otherwise the uncached-price term goes negative.
                usage["cache_read"] = u.get("cache_read_input_tokens", 0) or 0
                usage["cache_write"] = u.get("cache_creation_input_tokens", 0) or 0
                usage["input"] = ((u.get("input_tokens", 0) or 0)
                                  + usage["cache_read"] + usage["cache_write"])
            elif etype == "content_block_start":
                block = event.get("content_block") or {}
                idx = event.get("index", len(blocks))
                if block.get("type") == "tool_use":
                    blocks[idx] = {"kind": "tool", "id": block.get("id"),
                                   "name": block.get("name"), "json": ""}
                elif block.get("type") == "thinking":
                    blocks[idx] = {"kind": "thinking", "text": ""}
                else:
                    blocks[idx] = {"kind": "text", "text": ""}
            elif etype == "content_block_delta":
                delta = event.get("delta") or {}
                idx = event.get("index")
                slot = blocks.get(idx)
                if slot is None:
                    continue
                if delta.get("type") == "text_delta":
                    slot["text"] += delta.get("text", "")
                    yield ("text", delta.get("text", ""))
                elif delta.get("type") == "thinking_delta":
                    slot["text"] += delta.get("thinking", "")
                    yield ("reasoning", delta.get("thinking", ""))
                elif delta.get("type") == "input_json_delta":
                    slot["json"] += delta.get("partial_json", "")
            elif etype == "content_block_stop":
                slot = blocks.get(event.get("index"))
                if slot and slot["kind"] == "tool":
                    try:
                        args = json.loads(slot["json"] or "{}")
                    except ValueError:
                        args = {"_raw": slot["json"]}
                    slot["input"] = args
                    yield ("tool_use", {"id": slot["id"], "name": slot["name"], "input": args})
            elif etype == "message_delta":
                stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
                u = event.get("usage") or {}
                usage["output"] = u.get("output_tokens", usage["output"]) or 0
            elif etype == "error":
                err = event.get("error") or {}
                raise ProviderError(str(err.get("message") or err))
            elif etype == "message_stop":
                break

        content: List[Dict[str, Any]] = []
        for idx in sorted(blocks):
            slot = blocks[idx]
            if slot["kind"] == "text" and slot.get("text"):
                content.append(text_block(slot["text"]))
            elif slot["kind"] == "tool":
                content.append(tool_use_block(slot["id"], slot["name"], slot.get("input") or {}))
        yield ("usage", usage)
        yield ("stop", stop_reason)
        yield ("message", {"role": "assistant", "content": content})

    @staticmethod
    def _to_anthropic(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for msg in messages:
            content = [b for b in msg.get("content", []) if b.get("type") in
                       ("text", "tool_use", "tool_result")]
            if not content:
                continue
            # merge consecutive same-role messages (e.g. after compaction)
            if out and out[-1]["role"] == msg["role"]:
                out[-1]["content"].extend(content)
            else:
                out.append({"role": msg["role"], "content": content})
        # Anthropic requires the first message to be from the user.
        while out and out[0]["role"] != "user":
            out.pop(0)
        return out


# --------------------------------------------------------------------------
# Mock provider (offline testing / demo)
# --------------------------------------------------------------------------

DEMO_SCRIPT: List[Dict[str, Any]] = [
    {"role": "assistant", "content": [
        {"type": "text", "text": "Let me take a look around first."},
        {"type": "tool_use", "id": "t1", "name": "bash", "input": {"command": "echo hello from orca"}},
    ]},
    {"role": "assistant", "content": [
        {"type": "tool_use", "id": "t2", "name": "write_file",
         "input": {"path": "hello.py", "content": 'print("hello from orca")\n'}},
    ]},
    {"role": "assistant", "content": [
        {"type": "text", "text": "Created `hello.py` and ran a command. "
                                 "This is an offline demo of the Orca Code UI — "
                                 "connect a real provider with `orca config`."},
    ]},
]


class MockProvider(BaseProvider):
    """Replays a scripted list of assistant messages. Zero network."""

    name = "mock"
    kind = "mock"

    def __init__(self, conf=None, model="mock-1", script=None, transport=None, max_tokens=None):
        super().__init__(conf or {"name": "mock", "kind": "mock", "base_url": "", "api_key": "",
                                  "headers": {}}, model, transport, max_tokens)
        if script is None:
            env_script = os.environ.get("ORCA_MOCK")
            if env_script and Path(env_script).is_file():
                script = json.loads(Path(env_script).read_text(encoding="utf-8"))
            else:
                script = DEMO_SCRIPT
        self.script = script
        self._i = 0

    def stream(self, system, messages, tools=None):
        if self._i >= len(self.script):
            msg = {"role": "assistant", "content": [text_block("(script exhausted)")]}
        else:
            msg = self.script[self._i]
            self._i += 1
        for block in msg["content"]:
            if block.get("type") == "text":
                yield ("text", block["text"])
            elif block.get("type") == "reasoning":
                yield ("reasoning", block["text"])
            elif block.get("type") == "tool_use":
                yield ("tool_use", {"id": block["id"], "name": block["name"],
                                    "input": block.get("input") or {}})
        est = sum(len(json.dumps(m)) for m in messages) // 4 + len(system) // 4
        yield ("usage", {"input": est, "output": 100, "cache_read": 0, "cache_write": 0})
        yield ("stop", "end_turn")
        # thinking is display-only, exactly like the real providers
        clean = {"role": "assistant",
                 "content": [b for b in msg["content"] if b.get("type") != "reasoning"]}
        yield ("message", clean)


# --------------------------------------------------------------------------
# Live model listing
# --------------------------------------------------------------------------

def list_remote_models(provider: BaseProvider,
                       transport: Optional[Transport] = None) -> List[str]:
    """Fetch the provider's live /v1/models list. Raises ProviderError."""
    transport = transport or provider.transport
    conf = provider.conf
    if provider.kind == "anthropic":
        url = f"{conf['base_url']}/v1/models?limit=100"
        headers = {"x-api-key": conf.get("api_key") or "",
                   "anthropic-version": "2023-06-01"}
    else:
        url = f"{conf['base_url']}/models"
        headers = {"Content-Type": "application/json"}
        if conf.get("api_key"):
            headers["Authorization"] = f"Bearer {conf['api_key']}"
    headers.update(conf.get("headers") or {})
    data = json.loads(transport.get(url, headers))
    out = [m.get("id") for m in data.get("data", []) if m.get("id")]
    return sorted(out)


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------

def make_provider(cfg: Config, name: Optional[str] = None, model: Optional[str] = None,
                  transport: Optional[Transport] = None) -> BaseProvider:
    name = (name or cfg.detect_provider()).lower()
    if name == "mock":
        return MockProvider(transport=transport, model=model or "mock-1")
    conf = cfg.resolve_provider(name)
    model = model or cfg.model or _default_model(cfg, name)
    if conf["kind"] == "anthropic":
        return AnthropicProvider(conf, model, transport=transport, max_tokens=cfg.max_tokens,
                                 prompt_caching=cfg.get("prompt_caching", True))
    return OpenAICompatProvider(conf, model, transport=transport, max_tokens=cfg.max_tokens)


def _default_model(cfg: Config, name: str) -> Optional[str]:
    if cfg.model and (cfg.provider in (None, name)):
        return cfg.model
    from .config import SUGGESTED_MODELS
    models = SUGGESTED_MODELS.get(name) or []
    return models[0] if models else None


def require_key(provider: BaseProvider) -> None:
    """Friendly error for missing API keys (checked lazily at first call)."""
    if provider.conf.get("name") in ("ollama", "lmstudio", "mock"):
        return
    if not provider.conf.get("api_key"):
        raise ProviderError(
            f"No API key for provider '{provider.conf.get('name')}'. "
            f"Run `orca config` or export the provider's key environment variable."
        )
