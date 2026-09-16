"""Event spine: everything the agent does is announced, nothing is silent.

The UI is just a subscriber; tests are subscribers; logs can be subscribers.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List


class EKind(str, Enum):
    session_start = "session_start"
    turn_start = "turn_start"
    user = "user"
    text = "text"
    thinking = "thinking"
    tool_start = "tool_start"
    tool_end = "tool_end"
    turn_end = "turn_end"
    task_start = "task_start"
    task_end = "task_end"
    budget = "budget"
    notice = "notice"
    error = "error"


@dataclass
class Event:
    kind: EKind
    data: Dict[str, Any] = field(default_factory=dict)


Subscriber = Callable[[Event], None]


class Bus:
    """A tiny synchronous event bus."""

    def __init__(self) -> None:
        self._subs: List[Subscriber] = []

    def subscribe(self, fn: Subscriber) -> Subscriber:
        self._subs.append(fn)
        return fn

    def emit(self, kind: EKind, **data: Any) -> Event:
        event = Event(kind, data)
        for fn in list(self._subs):
            fn(event)
        return event


class Recorder:
    """Bus subscriber that records every event — the test harness."""

    def __init__(self) -> None:
        self.events: List[Event] = []

    def __call__(self, event: Event) -> None:
        self.events.append(event)

    def of(self, kind: EKind) -> List[Event]:
        return [e for e in self.events if e.kind == kind]

    def kinds(self):
        return [e.kind for e in self.events]
