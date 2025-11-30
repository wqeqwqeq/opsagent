"""
Observability module for agent middleware.

Provides real-time streaming of agent thinking events to the frontend.
Events are emitted via a thread-safe EventStream that decouples
middleware execution from HTTP response handling.
"""

import queue
from typing import Optional

from agent_framework import agent_middleware, function_middleware


class EventStream:
    """Thread-safe event stream for middleware to push thinking events.

    This class provides a bridge between async middleware (running inside
    the workflow) and the sync Flask SSE endpoint. Events are pushed to
    a queue and consumed by the SSE generator.
    """

    def __init__(self):
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._active = False

    def start(self):
        """Start accepting events."""
        self._active = True
        # Clear any old events
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def emit(self, message: str):
        """Emit an event to the stream."""
        if self._active:
            self._queue.put(message)

    def stop(self):
        """Stop the stream and signal completion."""
        self._active = False
        self._queue.put(None)  # Sentinel to signal end

    def iter_events(self):
        """Iterate over events (blocking). Yields until None sentinel."""
        while True:
            event = self._queue.get()
            if event is None:
                break
            yield event


# Global stream instance (per-request, will be set by Flask)
_current_stream: Optional[EventStream] = None


def set_current_stream(stream: Optional[EventStream]):
    """Set the current stream for middleware to use."""
    global _current_stream
    _current_stream = stream


def get_current_stream() -> Optional[EventStream]:
    """Get the current stream."""
    return _current_stream


@agent_middleware
async def observability_agent_middleware(context, next):  # type: ignore
    """Log agent invocation and completion.

    Emits events when an agent starts and finishes execution.
    Format: "[AgentName] agent invoked" and "[AgentName] agent finished"
    """
    stream = get_current_stream()
    agent_name = context.agent.name

    if stream:
        stream.emit(f"[{agent_name}] agent invoked\n")

    await next(context)

    if stream:
        stream.emit(f"[{agent_name}] agent finished\n")


@function_middleware
async def observability_function_middleware(context, next):  # type: ignore
    """Log function/tool calls.

    Emits events when a tool is called and when it completes.
    Format: "Calling {function_name}..." and "{function_name} finished"
    """
    stream = get_current_stream()
    func_name = context.function.name

    if stream:
        stream.emit(f"Calling {func_name}...\n")

    await next(context)

    if stream:
        stream.emit(f"{func_name} finished\n")
