# Agent Observability & "Thinking" Stream

## Overview

This document describes the implementation of real-time agent observability in the OpsAgent UI. When users send a message, they see a "Thinking..." indicator that displays what the agents are doing in real-time.

## Architecture

### Key Design Decision

- **Workflow uses `run()` (NOT `run_stream()`)** - workflow logic remains unchanged
- **Middleware logs via a separate streaming mechanism** - side-channel for thinking events
- **Two independent streams to frontend**:
  1. SSE stream for thinking events (real-time)
  2. Regular HTTP response for final workflow result

### Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Frontend                                                                │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  Thinking...                      ◄── SSE Stream (thinking events) │  │
│  │  ├─ [Triage] agent invoked                                         │  │
│  │  ├─ [Triage] agent finished                                        │  │
│  │  ├─ [ServiceNow] agent invoked                                     │  │
│  │  ├─ Calling list_change_requests...                                │  │
│  │  └─ list_change_requests finished                                  │  │
│  ├────────────────────────────────────────────────────────────────────┤  │
│  │  Final Response                   ◄── HTTP Response (workflow.run) │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Event Flow

```
Frontend                          Flask                           Middleware
   │                                │                                 │
   ├─ GET /thinking (SSE) ─────────►│                                 │
   │                                ├─ Create EventStream             │
   │◄── SSE connection opened ──────│                                 │
   │                                │                                 │
   ├─ POST /messages ──────────────►│                                 │
   │                                ├─ set_current_stream(stream)     │
   │                                ├─ workflow.run() ───────────────►│
   │                                │                                 │
   │◄── data: [Triage] agent invoked ─────────────────────────────────┤
   │◄── data: [Triage] agent finished ────────────────────────────────┤
   │◄── data: [ServiceNow] agent invoked ─────────────────────────────┤
   │◄── data: Calling list_change_requests... ────────────────────────┤
   │◄── data: list_change_requests finished ──────────────────────────┤
   │◄── data: [ServiceNow] agent finished ────────────────────────────┤
   │                                │                                 │
   │                                │◄── workflow completes ──────────┤
   │                                ├─ stream.stop()                  │
   │◄── SSE closes ─────────────────│                                 │
   │                                │                                 │
   │◄── HTTP response (final) ──────│                                 │
```

## Implementation Details

### 1. Middleware Pattern

We use the Microsoft Agent Framework's decorator-based middleware:

```python
from agent_framework import agent_middleware, function_middleware

@agent_middleware
async def observability_agent_middleware(context, next):
    stream = get_current_stream()
    agent_name = context.agent.name

    if stream:
        stream.emit(f"[{agent_name}] agent invoked\n")

    await next(context)

    if stream:
        stream.emit(f"[{agent_name}] agent finished\n")

@function_middleware
async def observability_function_middleware(context, next):
    stream = get_current_stream()
    func_name = context.function.name

    if stream:
        stream.emit(f"Calling {func_name}...\n")

    await next(context)

    if stream:
        stream.emit(f"{func_name} finished\n")
```

### 2. EventStream Class

Thread-safe queue for cross-thread communication between async middleware and sync Flask:

```python
class EventStream:
    def __init__(self):
        self._queue: queue.Queue[Optional[str]] = queue.Queue()
        self._active = False

    def start(self):
        self._active = True

    def emit(self, message: str):
        if self._active:
            self._queue.put(message)

    def stop(self):
        self._active = False
        self._queue.put(None)  # Sentinel

    def iter_events(self):
        while True:
            event = self._queue.get()
            if event is None:
                break
            yield event
```

### 3. Two Endpoints Coordination

The `/thinking` SSE endpoint and `/messages` POST endpoint coordinate via a shared dict:

```python
_active_streams: dict[str, EventStream] = {}

# /thinking creates the stream
@app.route('/api/conversations/<conversation_id>/thinking')
def api_thinking_stream(conversation_id):
    stream = EventStream()
    _active_streams[conversation_id] = stream
    stream.start()
    # ... yield events ...

# /messages uses the stream
@app.route('/api/conversations/<conversation_id>/messages', methods=['POST'])
def api_send_message(conversation_id):
    stream = _active_streams.get(conversation_id)
    set_current_stream(stream)
    # ... run workflow ...
    stream.stop()
```

### 4. Frontend Flow

```javascript
// 1. Start SSE connection FIRST
const eventSource = new EventSource(`/api/conversations/${id}/thinking`);
eventSource.onmessage = (event) => appendThinkingEvent(event.data);

// 2. Then send the message
const response = await sendMessage(id, message);

// 3. Close SSE when done
eventSource.close();

// 4. Show final response
replaceThinkingWithResponse(response.assistant_message.content);
```

## Files Modified

| File | Changes |
|------|---------|
| `opsagent/observability.py` | New - EventStream class + middleware |
| `opsagent/agents/triage_agent.py` | Add middleware to ChatAgent |
| `opsagent/agents/servicenow_agent.py` | Add middleware to ChatAgent |
| `opsagent/agents/log_analytics_agent.py` | Add middleware to ChatAgent |
| `opsagent/agents/service_health_agent.py` | Add middleware to ChatAgent |
| `flask_app.py` | Add `/thinking` SSE endpoint |
| `opsagent/ui/app/static/script.js` | EventSource handling |
| `opsagent/ui/app/static/styles.css` | Thinking indicator styles |

## Key Points

1. **Workflow unchanged**: Still uses `run()`, not `run_stream()`
2. **Decoupled streams**: Thinking events via SSE, final response via HTTP
3. **Thread-safe**: `queue.Queue` works across async/sync boundaries
4. **Graceful cleanup**: Stream stops when workflow completes
5. **No database changes**: Events are ephemeral, only streamed

## Example Output

User asks: "What change requests are open and is Databricks healthy?"

```
Thinking...
├─ [Triage] agent invoked
├─ [Triage] agent finished
├─ [ServiceNow] agent invoked
├─ Calling list_change_requests...
├─ list_change_requests finished
├─ [ServiceNow] agent finished
├─ [Service Health] agent invoked
├─ Calling check_databricks_health...
├─ check_databricks_health finished
└─ [Service Health] agent finished

[Final response replaces thinking indicator]
```
