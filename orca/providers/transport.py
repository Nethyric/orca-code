"""HTTP/SSE transport with capped retries, jitter, and stream resilience.

Lessons priced in:
- gateways report transient hiccups as HTTP 400 with a body like
  "i/o timeout" — retry those too;
- streams die mid-flight: if nothing was yielded yet, retry the request;
  if content already flowed, surface a clean error instead of a hang;
- every socket has a timeout — nothing waits forever.
"""
import json
import random
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
TRANSIENT_BODY = ("i/o timeout", "timed out", "timeout", "temporarily",
                  "try again", "overloaded", "connection reset", "econnreset",
                  "server error", "queue is full")


class TransportError(Exception):
    """Terminal transport failure after retries (or a non-retryable one)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class StreamInterrupted(TransportError):
    """The stream died after yielding events; partial content was kept."""

    def __init__(self, message: str, partial: List[Dict[str, Any]]):
        super().__init__(message)
        self.partial = partial


@dataclass
class RetryPolicy:
    attempts: int = 3
    base: float = 2.0
    cap: float = 8.0
    jitter: float = 0.6

    def delay(self, attempt: int) -> float:
        # 2^n capped, plus jitter so a fleet of clients never syncs up
        return min(self.cap, self.base ** attempt) + random.uniform(0, self.jitter)


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", "replace")
    except Exception:
        raw = ""
    if raw:
        try:
            data = json.loads(raw)
            err = data.get("error", data)
            if isinstance(err, dict):
                return str(err.get("message") or raw)
            return str(err or raw)
        except ValueError:
            return raw[:400]
    return str(exc.reason)


def _looks_transient(status: int, detail: str) -> bool:
    if status in RETRYABLE_STATUS:
        return True
    lowered = (detail or "").lower()
    return any(marker in lowered for marker in TRANSIENT_BODY)


def parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one `data:` line; returns None for anything else."""
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        return json.loads(payload)
    except ValueError:
        return None


def iter_sse(stream) -> Iterator[Dict[str, Any]]:
    """Yield parsed SSE payloads from a binary stream, with a read timeout."""
    for raw in stream:
        line = raw.decode("utf-8", "replace").rstrip("\n").rstrip("\r")
        if line.startswith("event:") or not line:
            continue
        event = parse_sse_line(line)
        if event is not None:
            yield event


class Transport:
    """POST JSON, stream SSE back, retry what is worth retrying."""

    def __init__(self, policy: Optional[RetryPolicy] = None,
                 timeout: float = 120.0):
        self.policy = policy or RetryPolicy()
        self.timeout = timeout

    def post(self, url: str, headers: Dict[str, str],
             payload: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        for key, value in headers.items():
            req.add_header(key, value)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "text/event-stream")

        attempt = 0
        while True:
            try:
                resp = urllib.request.urlopen(req, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                detail = _error_detail(exc)
                if attempt + 1 < self.policy.attempts and _looks_transient(
                        exc.code, detail):
                    self._sleep(attempt)
                    attempt += 1
                    continue
                raise TransportError(f"HTTP {exc.code}: {detail}", exc.code)
            except (urllib.error.URLError, socket.timeout, OSError) as exc:
                if attempt + 1 < self.policy.attempts:
                    self._sleep(attempt)
                    attempt += 1
                    continue
                raise TransportError(str(exc))

            # stream phase: retry only if nothing has flowed yet
            collected: List[Dict[str, Any]] = []
            try:
                for event in iter_sse(resp):
                    collected.append(event)
                    yield event
                return
            except (urllib.error.HTTPError, urllib.error.URLError,
                    socket.timeout, OSError) as exc:
                if not collected and attempt + 1 < self.policy.attempts:
                    self._sleep(attempt)
                    attempt += 1
                    continue
                raise StreamInterrupted(
                    f"stream failed mid-response: {exc}", collected)

    def _sleep(self, attempt: int) -> None:
        time.sleep(self.policy.delay(attempt))
