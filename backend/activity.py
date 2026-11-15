"""Live activity events: steps inside a request report here and the streaming endpoint forwards them."""

import asyncio
import time
import uuid
from contextvars import ContextVar

MAX_LOG = 400

sink: ContextVar = ContextVar("activity_sink", default=None)
stage: ContextVar = ContextVar("activity_stage", default="")


class Sink:
    """Queue of events for one request, plus a capped log of the activity events to save with the answer."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.log: list = []

    def put(self, event: dict) -> None:
        if event.get("type") == "activity" and len(self.log) < MAX_LOG:
            self.log.append(event)
        self.queue.put_nowait(event)


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def clip(text, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def emit(kind: str, **data) -> None:
    """Report one step. Does nothing outside a streaming request."""
    s = sink.get()
    if s is not None:
        s.put({"type": "activity", "kind": kind, "stage": stage.get(), "at": time.time(), **data})
