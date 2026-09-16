"""Smart context management — Orca's killer feature.

Three layers of defense against context-window exhaustion:
  1. Tool-output hygiene  — bash/read results are truncated at the source
  2. Pruning              — old oversized tool results are head/tail-clipped
  3. Compaction           — when usage crosses the threshold, older turns are
                            summarized by the model and replaced by one dense
                            summary message; recent turns are kept verbatim.

Token estimates are calibrated against the exact usage the API reports.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .config import Config, model_info

# Rough chars-per-token for code/mixed English (calibrated over time).
_CHARS_PER_TOKEN = 3.8
_PER_MESSAGE_OVERHEAD = 12


def estimate_text(text: str) -> int:
    if not text:
        return 0
    return int(len(text) / _CHARS_PER_TOKEN) + 1


def estimate_messages(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        total += _PER_MESSAGE_OVERHEAD
        for block in msg.get("content", []):
            btype = block.get("type")
            if btype == "text":
                total += estimate_text(block.get("text", ""))
            elif btype == "tool_use":
                total += estimate_text(json.dumps(block.get("input") or {})) + 24
            elif btype == "tool_result":
                content = block.get("content", "")
                if not isinstance(content, str):
                    content = json.dumps(content)
                total += estimate_text(content) + 16
    return total


COMPACT_SYSTEM = (
    "You are a precise session summarizer for a coding agent. Summarize the "
    "conversation so work can continue seamlessly after context compaction."
)

COMPACT_PROMPT = """\
Summarize this coding session for continuation after context compaction.

Include, as terse structured markdown:
1. **Goal** — the user's original goal and any changed requirements
2. **Done** — work completed: files created/edited (exact paths), commands run, bugs fixed
3. **Facts** — key discoveries: architecture, conventions, gotchas, relevant snippets
4. **Next** — current state, next steps, unresolved issues
5. **Preferences** — anything the user asked you to do or avoid

Rules: keep every file path and identifier exact; be dense and factual;
no pleasantries; max ~600 words.

<conversation>
{transcript}
</conversation>"""


class ContextManager:
    def __init__(self, cfg: Config, model: str):
        self.cfg = cfg
        self.info = model_info(model)
        self.window: int = self.info.get("context", 128_000)
        self.calibration = 1.0          # estimate → actual scale
        self.last_exact: Optional[int] = None
        self.compactions = 0

    # -- accounting ----------------------------------------------------------

    def calibrate(self, reported_input_tokens: Optional[int], system: str,
                  messages: List[Dict[str, Any]], tools_json: str) -> None:
        if not reported_input_tokens:
            return
        estimate = estimate_text(system) + estimate_text(tools_json) + estimate_messages(messages)
        if estimate <= 0:
            return
        ratio = reported_input_tokens / estimate
        # exponential moving average, clamped to sane bounds
        self.calibration = max(0.5, min(3.0, 0.6 * self.calibration + 0.4 * ratio))
        self.last_exact = reported_input_tokens

    def used(self, system: str, messages: List[Dict[str, Any]], tools_json: str) -> int:
        estimate = estimate_text(system) + estimate_text(tools_json) + estimate_messages(messages)
        return int(estimate * self.calibration)

    # -- compaction ----------------------------------------------------------

    def should_compact(self, used: int) -> bool:
        if not self.cfg.get("auto_compact", True):
            return False
        return used >= int(self.window * float(self.cfg.get("compact_threshold", 0.82)))

    def maybe_compact(self, system: str, messages: List[Dict[str, Any]], tools_json: str,
                      summarizer, extra_context: str = ""
                      ) -> Optional[List[Dict[str, Any]]]:
        """Called by the agent between turns. Returns new messages if compacted."""
        used = self.used(system, messages, tools_json)
        if not self.should_compact(used):
            return None
        return self.compact(system, messages, tools_json, summarizer,
                            extra_context=extra_context)

    def compact(self, system: str, messages: List[Dict[str, Any]], tools_json: str,
                summarizer, extra_context: str = "") -> List[Dict[str, Any]]:
        """summarizer(prompt_system, prompt_text) -> summary str."""
        keep_budget = int(self.window * float(self.cfg.get("keep_recent", 0.30)))

        # never compact away the current exchange: always keep the tail.
        recent, older = _split_turns(messages, keep_budget)

        # Layer 2: prune oversized old tool results first.
        older, pruned = _prune_tool_results(older)
        if not older:
            return messages  # nothing old enough to compact

        transcript = _render_transcript(older)
        summary = None
        try:
            summary = summarizer(COMPACT_SYSTEM, COMPACT_PROMPT.format(transcript=transcript))
        except Exception:
            summary = None
        if not summary:
            summary = (
                "(Compaction fallback — automatic summary failed; older turns were dropped.)\n"
                + _render_transcript(older)[:8000]
            )

        summary_msg = {
            "role": "user",
            "content": [{
                "type": "text",
                "text": (
                    "[Context compacted — earlier conversation was summarized. "
                    "This summary is authoritative; the verbatim turns are gone.]\n\n"
                    + summary.strip()
                    + (f"\n\n{extra_context.strip()}" if extra_context.strip() else "")
                ),
            }],
        }
        self.compactions += 1
        return [summary_msg] + recent

    # -- reporting ------------------------------------------------------------

    def breakdown(self, system: str, messages: List[Dict[str, Any]], tools_json: str
                  ) -> Dict[str, int]:
        tool_tokens = estimate_text(tools_json)
        system_tokens = estimate_text(system)
        user = assistant = results = 0
        overhead = len(messages) * _PER_MESSAGE_OVERHEAD
        for msg in messages:
            for block in msg.get("content", []):
                btype = block.get("type")
                if btype == "text":
                    if msg["role"] == "user":
                        user += estimate_text(block.get("text", ""))
                    else:
                        assistant += estimate_text(block.get("text", ""))
                elif btype == "tool_use":
                    assistant += estimate_text(json.dumps(block.get("input") or {})) + 24
                elif btype == "tool_result":
                    results += estimate_text(str(block.get("content", ""))) + 16
        scale = self.calibration
        parts = {
            "system": system_tokens * scale,
            "tools": tool_tokens * scale,
            "user": user * scale,
            "assistant": assistant * scale,
            "tool results": results * scale,
        }
        out = {k: int(v) for k, v in parts.items()}
        # guarantee the displayed parts add up exactly to the reported total
        out["overhead"] = self.used(system, messages, tools_json) - sum(out.values())
        return out


# --------------------------------------------------------------------------
# internals
# --------------------------------------------------------------------------

def _turn_start_indices(messages: List[Dict[str, Any]]) -> List[int]:
    """Indices where a *user text* message begins (tool_result messages don't
    start turns — they continue the current one)."""
    starts: List[int] = []
    for i, msg in enumerate(messages):
        if msg.get("role") != "user":
            continue
        if any(block.get("type") == "text" for block in msg.get("content", [])):
            starts.append(i)
    return starts


def _split_turns(messages: List[Dict[str, Any]], keep_budget_tokens: int
                 ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split at a turn boundary so `recent` starts a clean user message.
    Always keeps at least the final turn verbatim. If the whole history fits
    in the budget nothing is split off."""
    if len(messages) <= 2:
        return messages, []
    starts = _turn_start_indices(messages)
    if len(starts) <= 1:
        return messages, []          # single exchange: nothing safe to drop
    acc = 0
    split_at: Optional[int] = None
    for idx in range(len(starts) - 1, 0, -1):
        start = starts[idx]
        end = starts[idx + 1] if idx + 1 < len(starts) else len(messages)
        acc += estimate_messages(messages[start:end])
        if acc > keep_budget_tokens:
            split_at = start
            break
    if split_at is None or split_at <= 0:
        return messages, []
    return messages[split_at:], messages[:split_at]


def _prune_tool_results(messages: List[Dict[str, Any]], limit: int = 800
                        ) -> Tuple[List[Dict[str, Any]], int]:
    """Head/tail-clip oversized old tool results. Returns (messages, n_pruned)."""
    pruned = 0
    out: List[Dict[str, Any]] = []
    for msg in messages:
        blocks = []
        for block in msg.get("content", []):
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, str) and len(content) > limit:
                    blocks.append({
                        **block,
                        "content": content[: limit // 2]
                        + f"\n⋯ [pruned {len(content) - limit} chars during compaction] ⋯\n"
                        + content[-limit // 2:],
                    })
                    pruned += 1
                    continue
            blocks.append(block)
        out.append({**msg, "content": blocks})
    return out, pruned


def _render_transcript(messages: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for msg in messages:
        who = "USER" if msg.get("role") == "user" else "ASSISTANT"
        for block in msg.get("content", []):
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "")
                lines.append(f"{who}: {text[:4000]}")
            elif btype == "tool_use":
                args = json.dumps(block.get("input") or {})
                if len(args) > 1500:
                    args = args[:1500] + "…"
                lines.append(f"ASSISTANT tool call {block.get('name')}({args})")
            elif btype == "tool_result":
                content = str(block.get("content", ""))
                if len(content) > 1200:
                    content = content[:600] + " ⋯ " + content[-400:]
                lines.append(f"TOOL RESULT: {content}")
    return "\n".join(lines)[:120_000]
