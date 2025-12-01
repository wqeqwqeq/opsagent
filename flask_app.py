"""
flask_app.py
Flask-based chat UI backend with REST API endpoints.
Supports persistent chat history via PostgreSQL/Redis/Local storage.
"""
import asyncio
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, List

from flask import Flask, jsonify, request, send_from_directory, Response, stream_with_context
from flask_cors import CORS
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, AzureCliCredential
from azure.storage.blob import BlobServiceClient

from agent_framework import ChatMessage, Role
from agent_framework.observability import setup_observability
from opsagent.workflows.triage_workflow import create_triage_workflow, WorkflowInput
from opsagent.ui.app.storage import ChatHistoryManager
from opsagent.observability import EventStream, set_current_stream
from opsagent.utils import AKV

# Load environment variables from .env file
load_dotenv()

# Setup OpenTelemetry observability (traces to Application Insights)
setup_observability(
     enable_sensitive_data=True
)

# ----------------------------------------------------------------------------
# Flask App Configuration
# ----------------------------------------------------------------------------
app = Flask(__name__, static_folder='opsagent/ui/app/static')
CORS(app)

DEFAULT_MODEL = "gpt-4o-mini"

# Configure logging
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------------
# Azure Storage Configuration
# ----------------------------------------------------------------------------
RESOURCE_PREFIX = os.getenv('RESOURCE_PREFIX', 'stanley-dev-ui')
STORAGE_ACCOUNT_NAME = f"{RESOURCE_PREFIX.replace('-', '')}stg"
KEY_VAULT_NAME = f"{RESOURCE_PREFIX.replace('-', '')}kv"
CONTAINER_NAME = 'standup-recordings'

# ----------------------------------------------------------------------------
# Initialize Azure Key Vault Client
# ----------------------------------------------------------------------------
akv = AKV(vault_name =  KEY_VAULT_NAME)

# ----------------------------------------------------------------------------
# Initialize Chat History Manager
# ----------------------------------------------------------------------------
CHAT_HISTORY_MODE = os.getenv("CHAT_HISTORY_MODE", "local")
CONVERSATION_HISTORY_DAYS = int(os.getenv("CONVERSATION_HISTORY_DAYS", "7"))

if CHAT_HISTORY_MODE in ["redis", "local_redis"]:
    # Build PostgreSQL connection string from RESOURCE_PREFIX
    postgres_host = f"{RESOURCE_PREFIX}-postgres.postgres.database.azure.com"
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_ADMIN_LOGIN", "pgadmin")
    password = akv.get_secret("POSTGRES-ADMIN-PASSWORD") or ""
    database = os.getenv("POSTGRES_DATABASE", "chat_history")
    sslmode = os.getenv("POSTGRES_SSLMODE", "require")
    connection_string = f"postgresql://{user}:{password}@{postgres_host}:{port}/{database}?sslmode={sslmode}"

    # Build Redis connection parameters from RESOURCE_PREFIX
    redis_host = f"{RESOURCE_PREFIX}-redis.redis.cache.windows.net"
    redis_password = akv.get_secret("REDIS-PASSWORD") or ""
    redis_port = int(os.getenv("REDIS_PORT", "6380"))
    redis_ssl = os.getenv("REDIS_SSL", "true").lower() == "true"
    redis_ttl = int(os.getenv("REDIS_TTL_SECONDS", "1800"))

    HISTORY = ChatHistoryManager(
        mode="redis",
        connection_string=connection_string,
        redis_host=redis_host,
        redis_password=redis_password,
        redis_port=redis_port,
        redis_ssl=redis_ssl,
        redis_ttl=redis_ttl,
        history_days=CONVERSATION_HISTORY_DAYS
    )
elif CHAT_HISTORY_MODE == "postgres" or CHAT_HISTORY_MODE == "local_psql":
    # Build PostgreSQL connection string from RESOURCE_PREFIX
    postgres_host = f"{RESOURCE_PREFIX}-postgres.postgres.database.azure.com"
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_ADMIN_LOGIN", "pgadmin")
    password = akv.get_secret("POSTGRES-ADMIN-PASSWORD") or ""
    database = os.getenv("POSTGRES_DATABASE", "chat_history")
    sslmode = os.getenv("POSTGRES_SSLMODE", "require")
    connection_string = f"postgresql://{user}:{password}@{postgres_host}:{port}/{database}?sslmode={sslmode}"

    HISTORY = ChatHistoryManager(
        mode="postgres",
        connection_string=connection_string,
        history_days=CONVERSATION_HISTORY_DAYS
    )
else:
    HISTORY = ChatHistoryManager(mode="local")


# ----------------------------------------------------------------------------
# Initialize Workflow
# ----------------------------------------------------------------------------
WORKFLOW = create_triage_workflow()

# ----------------------------------------------------------------------------
# Thinking Stream Management
# ----------------------------------------------------------------------------
# Store active EventStream instances keyed by conversation_id
_active_streams: Dict[str, EventStream] = {}


# ----------------------------------------------------------------------------
# Authentication Helper
# ----------------------------------------------------------------------------
def get_user_info() -> Dict[str, str]:
    """Extract user information from SSO headers or environment config.

    Supports five modes:
    1. local_psql: Use hardcoded test credentials from environment (PostgreSQL only)
    2. local_redis: Use hardcoded test credentials from environment (Redis + PostgreSQL)
    3. postgres: Use real SSO headers from Azure Easy Auth (PostgreSQL only)
    4. redis: Use real SSO headers from Azure Easy Auth (Redis + PostgreSQL)
    5. local: Fallback for local JSON mode
    """
    # Check if we're in local testing mode (PostgreSQL or Redis)
    if CHAT_HISTORY_MODE in ["local_psql", "local_redis"]:
        return {
            'user_id': os.getenv('LOCAL_TEST_CLIENT_ID', '00000000-0000-0000-0000-000000000001'),
            'user_name': os.getenv('LOCAL_TEST_USERNAME', 'local_user'),
            'is_authenticated': True,
            'mode': CHAT_HISTORY_MODE
        }

    # Try to extract from SSO headers (postgres or redis mode)
    if CHAT_HISTORY_MODE in ["postgres", "redis"]:
        user_name = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME')
        user_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-ID')

        if user_id and user_name:
            return {
                'user_id': user_id,
                'user_name': user_name,
                'is_authenticated': True,
                'mode': CHAT_HISTORY_MODE
            }

    # Fallback for local mode or when SSO headers are unavailable
    return {
        'user_id': 'local_user',
        'user_name': 'Local User',
        'is_authenticated': False,
        'mode': 'local'
    }


# ----------------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------------
def title_from_first_user_message(msg: str) -> str:
    """Derive a short, single-line chat title from the user's first message."""
    trimmed = (msg or "New chat").strip().replace("\n", " ")
    return (trimmed[:28] + "…") if len(trimmed) > 29 else (trimmed if trimmed else "New chat")


def convert_messages(messages: List[Dict]) -> List[ChatMessage]:
    """Convert Flask message format to ChatMessage objects."""
    result = []
    for msg in messages:
        role = Role.USER if msg["role"] == "user" else Role.ASSISTANT
        result.append(ChatMessage(role, text=msg["content"]))
    return result


def call_llm(model: str, messages: List[Dict]) -> str:
    """Execute the triage workflow with conversation history."""
    try:
        chat_messages = convert_messages(messages)
        input_data = WorkflowInput(messages=chat_messages)

        # Run async workflow synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(WORKFLOW.run(input_data))
        finally:
            loop.close()

        # Extract output
        outputs = result.get_outputs()
        if outputs:
            return outputs[0]
        return "No response from workflow"

    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        return f"Error: Unable to process request. {str(e)}"


def build_llm_messages(messages: List[Dict]) -> List[Dict]:
    """Convert internal message dicts to an OpenAI-style message list."""
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def models_list() -> List[str]:
    """Return available model identifiers."""
    return [
        "gpt-4o-mini",
        "gpt-4o",
        "gpt-4.1",
        "gpt-3.5-turbo",
        "local-llm",
    ]


# ----------------------------------------------------------------------------
# Routes - Frontend
# ----------------------------------------------------------------------------
@app.route('/')
def index():
    """Serve the main frontend HTML page."""
    return send_from_directory('opsagent/ui/app/static', 'index.html')


# ----------------------------------------------------------------------------
# Routes - API Endpoints
# ----------------------------------------------------------------------------
@app.route('/api/user')
def api_user():
    """Get current user information from SSO headers or local config."""
    return jsonify(get_user_info())


@app.route('/api/models')
def api_models():
    """List available LLM models."""
    return jsonify(models_list())


@app.route('/api/conversations')
def api_conversations():
    """List all conversations for the current user, sorted by last_modified (newest first)."""
    user_info = get_user_info()
    user_id = user_info.get('user_id')

    # Get conversations from storage
    conversations = HISTORY.list_conversations(user_id=user_id)

    # Sort by last_modified DESC (newest first)
    sorted_convos = sorted(
        conversations,
        key=lambda x: x[1].get('last_modified', x[1].get('created_at', '')),
        reverse=True
    )

    # Return as list of objects for easier frontend consumption
    result = [
        {
            'id': cid,
            'title': convo.get('title'),
            'model': convo.get('model'),
            'created_at': convo.get('created_at'),
            'last_modified': convo.get('last_modified'),
            'messages': convo.get('messages', [])  # May be empty for lazy-loaded
        }
        for cid, convo in sorted_convos
    ]

    return jsonify(result)


@app.route('/api/conversations/<conversation_id>')
def api_get_conversation(conversation_id):
    """Get a specific conversation with all messages."""
    user_info = get_user_info()
    user_id = user_info.get('user_id')

    convo = HISTORY.get_conversation(conversation_id, user_id=user_id)

    if not convo:
        return jsonify({'error': 'Conversation not found'}), 404

    return jsonify({
        'id': conversation_id,
        'title': convo.get('title'),
        'model': convo.get('model'),
        'messages': convo.get('messages', []),
        'created_at': convo.get('created_at'),
        'last_modified': convo.get('last_modified')
    })


@app.route('/api/conversations', methods=['POST'])
def api_create_conversation():
    """Create a new conversation."""
    user_info = get_user_info()
    user_id = user_info.get('user_id')

    data = request.json or {}
    cid = str(uuid.uuid4())[:8]

    conversation = {
        'title': 'New chat',
        'model': data.get('model', DEFAULT_MODEL),
        'messages': [],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_modified': datetime.now(timezone.utc).isoformat()
    }

    HISTORY.save_conversation(cid, conversation, user_id=user_id)

    return jsonify({'id': cid, **conversation}), 201


@app.route('/api/conversations/<conversation_id>', methods=['PUT'])
def api_update_conversation(conversation_id):
    """Update a conversation (e.g., rename, change model)."""
    user_info = get_user_info()
    user_id = user_info.get('user_id')

    data = request.json or {}
    convo = HISTORY.get_conversation(conversation_id, user_id=user_id)

    if not convo:
        return jsonify({'error': 'Conversation not found'}), 404

    # Update title (don't update last_modified for rename)
    if 'title' in data:
        convo['title'] = data['title']

    # Update model (don't update last_modified for model change)
    if 'model' in data:
        convo['model'] = data['model']

    HISTORY.save_conversation(conversation_id, convo, user_id=user_id)

    return jsonify({'id': conversation_id, **convo})


@app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
def api_delete_conversation(conversation_id):
    """Delete a conversation."""
    user_info = get_user_info()
    user_id = user_info.get('user_id')

    HISTORY.delete_conversation(conversation_id, user_id=user_id)

    return '', 204


@app.route('/api/conversations/<conversation_id>/thinking')
def api_thinking_stream(conversation_id):
    """SSE endpoint for streaming thinking events during workflow execution.

    This endpoint should be connected BEFORE sending a message.
    Events are pushed by middleware during workflow.run() execution.
    """
    def generate():
        # Create and register stream for this conversation
        stream = EventStream()
        _active_streams[conversation_id] = stream
        stream.start()

        # Send initial comment to establish connection and flush buffers
        # This helps with Azure App Service proxy buffering
        yield ": connected\n\n"

        try:
            # Yield events as they arrive (blocking)
            for event in stream.iter_events():
                yield f"data: {event}\n\n"
        finally:
            # Cleanup when stream ends or client disconnects
            if conversation_id in _active_streams:
                del _active_streams[conversation_id]

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
            # Azure App Service specific - disable ARR buffering
            'X-ARR-Disable-Session-Affinity': 'true',
            'Transfer-Encoding': 'chunked',
        }
    )


@app.route('/api/conversations/<conversation_id>/messages', methods=['POST'])
def api_send_message(conversation_id):
    """Send a message to a conversation and get LLM response."""
    user_info = get_user_info()
    user_id = user_info.get('user_id')

    data = request.json or {}
    user_message = data.get('message', '').strip()

    if not user_message:
        return jsonify({'error': 'Message cannot be empty'}), 400

    # Get conversation
    convo = HISTORY.get_conversation(conversation_id, user_id=user_id)
    if not convo:
        return jsonify({'error': 'Conversation not found'}), 404

    # Append user message
    convo['messages'].append({
        'role': 'user',
        'content': user_message,
        'time': datetime.now(timezone.utc).isoformat()
    })

    # Auto-generate title from first message
    if convo['title'] == 'New chat':
        convo['title'] = title_from_first_user_message(user_message)

    # Get the thinking stream for this conversation (if frontend connected)
    stream = _active_streams.get(conversation_id)

    # Set as current stream for middleware to use
    set_current_stream(stream)

    try:
        # Call workflow (middleware will emit events to stream)
        reply = call_llm(convo['model'], build_llm_messages(convo['messages']))
    finally:
        # Stop the stream and clear current stream
        if stream:
            stream.stop()
        set_current_stream(None)

    # Append assistant message
    convo['messages'].append({
        'role': 'assistant',
        'content': reply,
        'time': datetime.now(timezone.utc).isoformat()
    })

    # Update last_modified (moves chat to top of list)
    convo['last_modified'] = datetime.now(timezone.utc).isoformat()

    # Save to storage (write-through: postgres first, then redis)
    HISTORY.save_conversation(conversation_id, convo, user_id=user_id)

    return jsonify({
        'user_message': convo['messages'][-2],
        'assistant_message': convo['messages'][-1],
        'title': convo['title']
    })


@app.route('/api/videos')
def api_list_videos():
    """List all videos in the standup-recordings container."""
    try:
        # Use appropriate credential based on environment
        if CHAT_HISTORY_MODE in ['local_redis', 'local_psql']:
            # Local development: Use Azure CLI credentials explicitly
            credential = AzureCliCredential()
            logger.info("Using Azure CLI credentials for local development")
        else:
            # Production: Use Managed Identity via DefaultAzureCredential
            credential = DefaultAzureCredential()
            logger.info("Using DefaultAzureCredential (Managed Identity) for production")

        account_url = f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net"

        # Create blob service client
        blob_service_client = BlobServiceClient(account_url, credential=credential)
        container_client = blob_service_client.get_container_client(CONTAINER_NAME)

        # List all .mp4 blobs
        videos = []
        for blob in container_client.list_blobs():
            if blob.name.endswith('.mp4'):
                # Extract title from filename (e.g., "2025-11-21-standup.mp4" -> "2025-11-21 Standup")
                title = blob.name.replace('.mp4', '').replace('-standup', ' Standup')

                videos.append({
                    'filename': blob.name,
                    'title': title,
                    'blob_url': f"{account_url}/{CONTAINER_NAME}/{blob.name}",
                    'last_modified': blob.last_modified.isoformat() if blob.last_modified else None,
                    'size_mb': round(blob.size / (1024 * 1024), 2) if blob.size else 0
                })

        # Sort by filename (most recent first)
        videos.sort(key=lambda x: x['filename'], reverse=True)

        return jsonify({'videos': videos}), 200

    except Exception as e:
        logger.error(f"Error listing videos: {str(e)}")
        return jsonify({'error': 'Failed to fetch videos', 'details': str(e)}), 500


# ----------------------------------------------------------------------------
# Main Entry Point
# ----------------------------------------------------------------------------
if __name__ == '__main__':
    # Development server (use Gunicorn for production)
    app.run(host='0.0.0.0', port=8000, debug=True)

