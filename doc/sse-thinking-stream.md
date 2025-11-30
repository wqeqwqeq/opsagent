# SSE Thinking Stream Implementation

This document describes the Server-Sent Events (SSE) implementation for streaming "thinking" events from agent middleware to the Flask UI.

## Overview

When a user sends a message, the triage workflow dispatches work to specialized agents. The thinking stream provides real-time visibility into:
- Agent invocations (`[AgentName] agent invoked/finished`)
- Tool/function calls (`Calling {tool_name}... / {tool_name} finished`)

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Frontend                                                                │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  Thinking...                      ◄── SSE Stream (thinking events) │  │
│  │  ├─ [Triage] agent invoked                                         │  │
│  │  ├─ [ServiceNow] agent invoked                                     │  │
│  │  ├─ Calling list_change_requests...                                │  │
│  │  └─ list_change_requests finished                                  │  │
│  ├────────────────────────────────────────────────────────────────────┤  │
│  │  Final Response                   ◄── HTTP Response (workflow.run) │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                    │                              │
                    ▼                              ▼
┌───────────────────────────────┐    ┌───────────────────────────────────┐
│  /api/.../thinking (SSE)      │    │  /api/.../messages (POST)         │
│  - EventStream class          │    │  - workflow.run() as before       │
│  - Middleware pushes events   │    │  - Returns final response         │
└───────────────────────────────┘    └───────────────────────────────────┘
                    ▲                              │
                    │                              ▼
┌───────────────────────────────────────────────────────────────────────────┐
│  Middleware (observability.py)                                            │
│  @agent_middleware + @function_middleware                                 │
│  - Emits events via thread-safe queue                                     │
└───────────────────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

1. **Workflow uses `run()` NOT `run_stream()`** - Workflow logic unchanged
2. **Middleware streaming is decoupled** - Side-channel for thinking events
3. **Two independent streams to frontend**:
   - SSE stream for thinking events (real-time)
   - Regular HTTP POST response for final workflow result

## Implementation Files

| File | Purpose |
|------|---------|
| `opsagent/observability.py` | EventStream class + middleware decorators |
| `flask_app.py` | `/api/conversations/<id>/thinking` SSE endpoint |
| `opsagent/agents/*.py` | All agents configured with middleware |
| `opsagent/ui/app/static/script.js` | EventSource SSE client |
| `opsagent/ui/app/static/styles.css` | Thinking indicator + flyout panel styles |

## Event Flow

```
Frontend                          Flask                           Middleware
   │                                │                                 │
   ├─ GET /thinking (SSE) ─────────►│                                 │
   │                                ├─ Create EventStream             │
   │◄── : connected ────────────────│                                 │
   │                                │                                 │
   ├─ POST /messages ──────────────►│                                 │
   │                                ├─ set_current_stream(stream)     │
   │                                ├─ workflow.run() ───────────────►│
   │                                │                                 │
   │◄── data: [Triage] agent invoked ──────────────────────────────────┤
   │◄── data: [ServiceNow] agent invoked ──────────────────────────────┤
   │◄── data: Calling list_change_requests... ─────────────────────────┤
   │◄── data: list_change_requests finished ───────────────────────────┤
   │◄── data: [ServiceNow] agent finished ─────────────────────────────┤
   │◄── data: [Triage] agent finished ─────────────────────────────────┤
   │                                │                                 │
   │                                │◄── workflow completes ──────────┤
   │                                ├─ stream.stop()                  │
   │◄── SSE closes ─────────────────│                                 │
   │                                │                                 │
   │◄── HTTP 200 (final response) ──│                                 │
```

---

## Deployment Issues & Solutions

### Issue 1: Docker Container - Multi-Worker Problem

**Symptom**: SSE works locally with `uv run flask_app.py` but not in Docker container.

**Root Cause**: Gunicorn with `-w 4` (4 worker processes) causes `_active_streams` dict to not be shared between workers.

```
┌─────────────────────────────────────────────────────────────┐
│  Container (Gunicorn -w 4)                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │
│  │  Worker 1   │  │  Worker 2   │  │  Worker 3   │  ...     │
│  │ _active_    │  │ _active_    │  │ _active_    │          │
│  │ streams={}  │  │ streams={}  │  │ streams={}  │          │
│  └─────────────┘  └─────────────┘  └─────────────┘          │
└─────────────────────────────────────────────────────────────┘
        ↑                    ↑
   SSE GET req          POST msg req
   (creates stream      (stream not found -
    in Worker 1)         routed to Worker 2!)
```

**Solution**: Use single worker with gevent async worker.

```dockerfile
# Dockerfile
CMD ["uv", "run", "gunicorn", "-b", "0.0.0.0:8000", "-w", "1", "-k", "gevent", "flask_app:app"]
```

```toml
# pyproject.toml - add gevent dependency
"gevent>=24.2.1",
```

---

### Issue 2: Azure App Service - Response Buffering

**Symptom**: SSE works in local Docker but not on Azure App Service.

**Root Cause**: Azure App Service's ARR (Application Request Routing) proxy buffers HTTP responses, preventing real-time SSE delivery.

**Solution**: Multiple fixes required:

#### 1. Enhanced Response Headers (flask_app.py)

```python
return Response(
    stream_with_context(generate()),
    mimetype='text/event-stream',
    headers={
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0',
        'X-Accel-Buffering': 'no',  # Nginx
        'X-Content-Type-Options': 'nosniff',
        'Content-Type': 'text/event-stream; charset=utf-8',
        # Azure App Service specific
        'X-ARR-Disable-Session-Affinity': 'true',
        'Transfer-Encoding': 'chunked',
    }
)
```

#### 2. Initial Connection Flush (flask_app.py)

```python
def generate():
    stream = EventStream()
    _active_streams[conversation_id] = stream
    stream.start()

    # Send initial comment to establish connection and flush buffers
    yield ": connected\n\n"

    try:
        for event in stream.iter_events():
            yield f"data: {event}\n\n"
    finally:
        if conversation_id in _active_streams:
            del _active_streams[conversation_id]
```

#### 3. Enable WebSockets in Bicep (simplified.bicep)

```bicep
siteConfig: {
  // ...
  webSocketsEnabled: true  // Helps with SSE long-lived connections
  // ...
}
```

#### 4. Azure Portal Settings (if needed)

- **Configuration → General settings → Web sockets**: Set to "On"
- **Configuration → General settings → ARR affinity**: Try setting to "Off"

---

## UI Components

### Thinking Indicator (during processing)

Shows real-time events as they stream in:
```
┌─────────────────────────────────────────┐
│  Thinking...                            │
│  ├─ [Triage] agent invoked              │
│  ├─ [ServiceNow] agent invoked          │
│  └─ Calling list_change_requests...     │
└─────────────────────────────────────────┘
```

### Collapsed State (after completion)

Clickable indicator that opens flyout:
```
┌─────────────────────────────────────────┐
│  ⊙ Thinking finished              ▸     │
└─────────────────────────────────────────┘
```

### Flyout Panel (full-height right sidebar)

```
┌────────────────────────────────────────┬─────────────────────┐
│  Main Panel (compressed)               │ Thinking        ✕   │
│                                        │─────────────────────│
│  [Chat content...]                     │ [Triage] invoked    │
│                                        │ [Triage] finished   │
│                                        │ [ServiceNow] invoked│
│                                        │ Calling list_cr...  │
│  [Input box...]                        │ [ServiceNow] done   │
└────────────────────────────────────────┴─────────────────────┘
```

---

## Troubleshooting

| Issue | Check |
|-------|-------|
| No events in local dev | Is middleware added to all agents? |
| No events in Docker | Is Gunicorn using `-w 1 -k gevent`? |
| No events on Azure | Check headers, WebSockets enabled, ARR settings |
| Events delayed/batched | Response buffering - check proxy settings |
| Connection closes early | Check timeout settings (Azure default: 230s) |

## Dependencies

- `gevent>=24.2.1` - Async worker for Gunicorn (handles concurrent SSE connections)
- `flask>=3.0.0` - Web framework with `stream_with_context`
- `gunicorn>=21.2.0` - WSGI server with gevent worker support
