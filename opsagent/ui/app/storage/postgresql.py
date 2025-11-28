"""PostgreSQL backend for chat history storage."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

try:
    import psycopg2
    from psycopg2 import pool, sql
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

logger = logging.getLogger(__name__)


class PostgreSQLBackend:
    """PostgreSQL backend for chat history storage.

    Stores conversations in two tables:
    - conversations: metadata (title, model, timestamps)
    - messages: individual chat messages with sequence numbers
    """

    def __init__(self, connection_string: str) -> None:
        """Initialize PostgreSQL backend with connection pool.

        Args:
            connection_string: PostgreSQL connection string
                Format: postgresql://user:pass@host:port/dbname?sslmode=require
        """
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError(
                "psycopg2 is required for PostgreSQL mode. "
                "Install with: pip install psycopg2-binary"
            )

        self.connection_string = connection_string

        try:
            # Create connection pool (min 1, max 5 connections)
            self.pool = psycopg2.pool.SimpleConnectionPool(
                1, 5, connection_string
            )
        except Exception as e:
            raise RuntimeError(f"Failed to connect to PostgreSQL: {e}")

    def _get_conn(self):
        """Get a connection from the pool."""
        return self.pool.getconn()

    def _put_conn(self, conn):
        """Return a connection to the pool."""
        self.pool.putconn(conn)

    def list_conversations(
        self, user_id: str, days: int = 7
    ) -> List[Tuple[str, Dict]]:
        """Return list of (conversation_id, conversation_metadata) for a user.

        Only returns conversations created within the last `days` days.
        Messages are NOT included in the returned data.

        Args:
            user_id: User client ID (Azure Entra ID or local test ID)
            days: Number of days of history to load (default: 7)

        Returns:
            List of (conversation_id, conversation_dict) tuples, sorted by last_modified DESC
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

                cur.execute(
                    """
                    SELECT conversation_id, user_client_id, title, model,
                           created_at, last_modified
                    FROM conversations
                    WHERE user_client_id = %s
                      AND created_at >= %s
                    ORDER BY last_modified DESC
                    """,
                    (user_id, cutoff_date)
                )

                rows = cur.fetchall()

                conversations = []
                for row in rows:
                    convo = {
                        "title": row["title"],
                        "model": row["model"],
                        "messages": [],  # Empty - not loaded yet
                        "created_at": row["created_at"].isoformat(),
                        "last_modified": row["last_modified"].isoformat(),
                    }
                    conversations.append((row["conversation_id"], convo))

                return conversations
        finally:
            self._put_conn(conn)

    def get_conversation(
        self, conversation_id: str, user_id: str
    ) -> Optional[Dict]:
        """Load a single conversation with all messages.

        Args:
            conversation_id: Conversation ID
            user_id: User client ID (for security check)

        Returns:
            Conversation dict with messages, or None if not found
        """
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get conversation metadata
                cur.execute(
                    """
                    SELECT conversation_id, user_client_id, title, model,
                           created_at, last_modified
                    FROM conversations
                    WHERE conversation_id = %s AND user_client_id = %s
                    """,
                    (conversation_id, user_id)
                )

                conv_row = cur.fetchone()
                if not conv_row:
                    return None

                # Get messages ordered by sequence number
                cur.execute(
                    """
                    SELECT role, content, timestamp, sequence_number
                    FROM messages
                    WHERE conversation_id = %s
                    ORDER BY sequence_number ASC
                    """,
                    (conversation_id,)
                )

                message_rows = cur.fetchall()

                messages = [
                    {
                        "role": msg["role"],
                        "content": msg["content"],
                        "time": msg["timestamp"].isoformat(),
                    }
                    for msg in message_rows
                ]

                return {
                    "title": conv_row["title"],
                    "model": conv_row["model"],
                    "messages": messages,
                    "created_at": conv_row["created_at"].isoformat(),
                    "last_modified": conv_row["last_modified"].isoformat(),
                }
        finally:
            self._put_conn(conn)

    def save_conversation(
        self, conversation_id: str, user_id: str, conversation: Dict
    ) -> None:
        """Save a conversation with all messages atomically.

        Uses a transaction to:
        1. UPSERT conversation metadata
        2. DELETE old messages
        3. INSERT new messages with sequence numbers

        Args:
            conversation_id: Conversation ID
            user_id: User client ID
            conversation: Conversation dict with messages
        """
        conn = self._get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    # Parse timestamps
                    created_at = datetime.fromisoformat(
                        conversation.get("created_at", datetime.now(timezone.utc).isoformat())
                    )
                    last_modified = datetime.fromisoformat(
                        conversation.get("last_modified", datetime.now(timezone.utc).isoformat())
                    )

                    # UPSERT conversation metadata
                    cur.execute(
                        """
                        INSERT INTO conversations
                            (conversation_id, user_client_id, title, model, created_at, last_modified)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (conversation_id)
                        DO UPDATE SET
                            title = EXCLUDED.title,
                            model = EXCLUDED.model,
                            last_modified = EXCLUDED.last_modified
                        """,
                        (
                            conversation_id,
                            user_id,
                            conversation["title"],
                            conversation["model"],
                            created_at,
                            last_modified,
                        )
                    )

                    # Delete old messages
                    cur.execute(
                        "DELETE FROM messages WHERE conversation_id = %s",
                        (conversation_id,)
                    )

                    # Insert new messages with sequence numbers
                    messages = conversation.get("messages", [])
                    for seq_num, msg in enumerate(messages):
                        timestamp = datetime.fromisoformat(
                            msg.get("time", datetime.now(timezone.utc).isoformat())
                        )

                        cur.execute(
                            """
                            INSERT INTO messages
                                (conversation_id, sequence_number, role, content, timestamp)
                            VALUES (%s, %s, %s, %s, %s)
                            """,
                            (
                                conversation_id,
                                seq_num,
                                msg["role"],
                                msg["content"],
                                timestamp,
                            )
                        )

                # Transaction commits automatically if no exception
        finally:
            self._put_conn(conn)

    def delete_conversation(
        self, conversation_id: str, user_id: str
    ) -> None:
        """Delete a conversation and all its messages.

        Args:
            conversation_id: Conversation ID
            user_id: User client ID (for security check)
        """
        conn = self._get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    # Messages are cascade-deleted by foreign key constraint
                    cur.execute(
                        """
                        DELETE FROM conversations
                        WHERE conversation_id = %s AND user_client_id = %s
                        """,
                        (conversation_id, user_id)
                    )
        finally:
            self._put_conn(conn)

    def close(self) -> None:
        """Close all connections in the pool."""
        if hasattr(self, 'pool'):
            self.pool.closeall()
