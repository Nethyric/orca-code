"""Provider adapters: turn internal messages into wire calls and back.

One adapter per protocol, not per vendor — the catalog carries the rest.
"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from .catalog import ProviderSpec, default_model
from .transport import StreamInterrupted, Transport, TransportError


class ProviderError(Exception):
    """A provider-level failure, already human-readable."""


@dataclass
class Reply:
    text: str = ""
    thinking: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    usage: Any = None            # core.budget.Usage
    stop_reason: str = ""


class BaseProvider:
    name = "base"
    model = ""

    def reply(self, messages: List[Dict[str, Any]],
              tools: Optional[List[Dict[str, Any]]],
              system: str = "") -> Reply:
        raise NotImplementedError


# --------------------------------------------------------------------- wire

def to_wire(messages: List[Dict[str, Any]], system: str) -> List[Dict[str, Any]]:
    """Internal blocks -> OpenAI chat-completions messages."""
    wire: List[Dict[str, Any]] = []
    if system:
        wire.append({"role": "system", "content": system})
    for msg in messages:
        role = msg["role"]
        blocks = msg.get("content") or []
        if role == "assistant":
            text = "".join(b.get("text", "") for b in blocks
                           if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function",
                      "function": {"name": b["name"],
                                   "arguments": json.dumps(b.get("input") or {})}}
                     for b in blocks if b.get("type") == "tool_use"]
            entry: Dict[str, Any] = {"role": "assistant",
                                     "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            wire.append(entry)
        elif role == "user":
            tool_results = [b for b in blocks if b.get("type") == "tool_result"]
            if tool_results:
                for r in tool_results:
                    wire.append({"role": "tool",
                                 "tool_call_id": r.get("tool_use_id", ""),
                                 "content": str(r.get("content", ""))})
            else:
                text = "".join(b.get("text", "") for b in blocks
                               if b.get("type") == "text")
                wire.append({"role": "user", "content": text})
    return wire


def _merge_tool_call(acc: Dict[int, Dict[str, Any]], delta: Dict[str, Any]) -> None:
    idx = int(delta.get("index", 0))
    slot = acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
    if delta.get("id"):
        slot["id"] = delta["id"]
    fn = delta.get("function") or {}
    if fn.get("name"):
        slot["name"] = slot["name"] + fn["name"]
    if fn.get("arguments"):
        slot["arguments"] = slot["arguments"] + fn["arguments"]


class OpenAICompatProvider(BaseProvider):
    """The one adapter most providers speak."""

    def __init__(self, spec: ProviderSpec, model: str,
                 api_key: str = "", transport: Optional[Transport] = None):
        self.spec = spec
        self.name = spec.name
        self.model = model or default_model(spec.name)
        self.api_key = api_key
        self.transport = transport or Transport()
        if not self.spec.base_url:
            raise ProviderError(
                f"provider '{spec.name}' needs base_url (custom endpoint)")

    def reply(self, messages: List[Dict[str, Any]],
              tools: Optional[List[Dict[str, Any]]],
              system: str = "") -> Reply:
        from ..core.budget import Usage

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": to_wire(messages, system),
            "stream": True,
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": t} for t in tools]
        headers = dict(self.spec.headers)
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        text_parts: List[str] = []
        think_parts: List[str] = []
        calls: Dict[int, Dict[str, Any]] = {}
        usage = Usage()
        stop_reason = ""
        try:
            for event in self.transport.post(
                    self.spec.base_url.rstrip("/") + "/chat/completions",
                    headers, payload):
                usage_delta = event.get("usage") or {}
                if usage_delta:
                    usage.input_tokens += int(usage_delta.get(
                        "prompt_tokens") or 0)
                    usage.output_tokens += int(usage_delta.get(
                        "completion_tokens") or 0)
                    details = usage_delta.get("prompt_tokens_details") or {}
                    usage.cache_read += int(details.get("cached_tokens") or 0)
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    stop_reason = str(choice["finish_reason"])
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    text_parts.append(str(delta["content"]))
                for key in ("reasoning", "reasoning_content"):
                    if delta.get(key):
                        think_parts.append(str(delta[key]))
                for td in delta.get("tool_calls") or []:
                    _merge_tool_call(calls, td)
        except StreamInterrupted as exc:
            raise ProviderError(
                f"{self.name}: {exc} — partial output kept, "
                "ask the model to continue")
        except TransportError as exc:
            raise ProviderError(f"{self.name}: {exc}")

        reply = Reply(text="".join(text_parts), thinking="".join(think_parts),
                      usage=usage, stop_reason=stop_reason)
        for idx in sorted(calls):
            slot = calls[idx]
            try:
                args = json.loads(slot["arguments"] or "{}")
            except ValueError:
                args = {"_raw": slot["arguments"]}
            reply.tool_calls.append({
                "id": slot["id"] or f"call_{idx}",
                "name": slot["name"],
                "input": args if isinstance(args, dict) else {"_raw": args},
            })
        return reply


class MockProvider(BaseProvider):
    """Scripted replies for tests and offline demos."""

    def __init__(self, script: Optional[List[Reply]] = None,
                 usage: Any = None, name: str = "mock", model: str = "mock-1"):
        self.script = list(script or [])
        self.usage = usage
        self.name = name
        self.model = model

    def reply(self, messages, tools, system: str = "") -> Reply:
        from ..core.budget import Usage
        if self.script:
            return self.script.pop(0)
        return Reply(text="done", usage=Usage(input_tokens=10,
                                              output_tokens=5, requests=1))


def make_provider(cfg, name: Optional[str] = None,
                  model: Optional[str] = None) -> BaseProvider:
    """Build a provider from config; raises ProviderError with guidance."""
    from .catalog import CATALOG

    prov = (name or cfg.get("provider") or cfg.detect_provider()).strip()
    spec = CATALOG.get(prov)
    if spec is None:
        raise ProviderError(
            f"unknown provider '{prov}' — see `orca --providers`")
    if spec.kind == "mock":
        return MockProvider()
    model = model or cfg.get("model") or default_model(prov)
    key = cfg.api_key(prov)
    if not key and not spec.local:
        env_hint = spec.key_env or "ORCA_API_KEY"
        raise ProviderError(
            f"no API key for '{prov}' — set {env_hint} or run `orca auth login`")
    base_url = (cfg.get("base_urls", {}).get(prov) or spec.base_url)
    from dataclasses import replace
    spec = replace(spec, base_url=base_url)
    return OpenAICompatProvider(spec, model, key or "local")
