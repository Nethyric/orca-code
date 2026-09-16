"""Message builders shared by the loop and the session store.

Kept dependency-free (no imports from loop or sessions) so both can use
them without cycles.
"""
from typing import Any, Dict, List, Optional


def user_msg(text: str) -> Dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant_msg(text: str, thinking: str = "",
                  tool_calls: Optional[List[Dict[str, Any]]] = None
                  ) -> Dict[str, Any]:
    blocks: List[Dict[str, Any]] = []
    if thinking:
        blocks.append({"type": "thinking", "thinking": thinking})
    if text:
        blocks.append({"type": "text", "text": text})
    for call in tool_calls or []:
        blocks.append({"type": "tool_use", "id": call["id"],
                       "name": call["name"], "input": call["input"]})
    return {"role": "assistant", "content": blocks or [{"type": "text",
                                                        "text": ""}]}


def tool_msg(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"role": "user", "content": results}
