"""Chat history manager with support for local JSON, PostgreSQL, and Redis storage."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .local import LocalBackend
from .postgresql import PostgreSQLBackend
from .redis import RedisBackend

logger = logging.getLogger(__name__)


class ChatHistoryManager:
    """Persist and retrieve chat histories.

    Modes:
      - "local": Store each conversation as a JSON file under .chat_history/
      - "postgres": Store conversations in PostgreSQL database
      - "redis": Store conversations in PostgreSQL with Redis write-through caching
    """

    def __init__(
        self,
        mode: str = "local",
        base_dir: Optional[Path | str] = None,
        connection_string: Optional[str] = None,
        history_days: int = 7,
        redis_host: Optional[str] = None,
        redis_password: Optional[str] = None,
        redis_port: int = 6380,
        redis_ssl: bool = True,
        redis_ttl: int = 1800,
    ) -> None:
        """Initialize chat history manager.

        Args:
            mode: Storage mode ("local", "postgres", or "redis")
            base_dir: Base directory for local mode
            connection_string: PostgreSQL connection string for postgres/redis mode
            history_days: Number of days of history to load (postgres/redis mode only)
            redis_host: Redis server hostname (redis mode only)
            redis_password: Redis password/access key (redis mode only)
            redis_port: Redis port (default: 6380 for Azure SSL)
            redis_ssl: Enable SSL/TLS connection (default: True for Azure)
            redis_ttl: TTL for Redis keys in seconds (default: 1800 = 30 minutes)
        """
        self.mode = mode
        self.history_days = history_days
        self.base_dir = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent
        self.cache = None

        if self.mode == "local":
            self.store_dir = self.base_dir / ".chat_history"
            self.backend = LocalBackend(self.store_dir)
        elif self.mode == "postgres":
            if not connection_string:
                raise ValueError("connection_string is required for postgres mode")
            self.backend = PostgreSQLBackend(connection_string)
        elif self.mode == "redis":
            # Initialize BOTH backends (decoupled)
            if not connection_string:
                raise ValueError("connection_string is required for redis mode")
            if not redis_host or not redis_password:
                raise ValueError("redis_host and redis_password are required for redis mode")

            self.backend = PostgreSQLBackend(connection_string)
            self.cache = RedisBackend(
                redis_host=redis_host,
                redis_password=redis_password,
                redis_port=redis_port,
                redis_ssl=redis_ssl,
                redis_ttl=redis_ttl
            )
        else:
            raise ValueError(f"Unsupported mode: {self.mode}")

    # ------------------------------
    # Public API
    # ------------------------------
    def list_conversations(self, user_id: Optional[str] = None) -> List[Tuple[str, Dict]]:
        """Return list of (conversation_id, conversation) from storage.

        Args:
            user_id: User client ID (required for postgres/redis mode)

        Returns:
            List of (conversation_id, conversation_dict) tuples
        """
        if self.mode == "local":
            return self.backend.list_conversations()

        elif self.mode == "postgres":
            if not user_id:
                raise ValueError("user_id is required for postgres mode")
            return self.backend.list_conversations(user_id, days=self.history_days)

        elif self.mode == "redis":
            if not user_id:
                raise ValueError("user_id is required for redis mode")

            # Try cache first
            if self.cache and self.cache.is_available():
                cached = self.cache.get_conversations_list(user_id, self.history_days)
                if cached is not None:
                    return cached

                # Cache miss - load from PostgreSQL
                logger.info(f"Cache miss for user {user_id}, loading from PostgreSQL")

            # Load from PostgreSQL
            conversations = self.backend.list_conversations(user_id, days=self.history_days)

            # Populate cache
            if self.cache and self.cache.is_available():
                self.cache.set_conversations_list(user_id, conversations)

            return conversations

        else:
            raise NotImplementedError(f"Mode {self.mode} not implemented")

    def get_conversation(
        self, conversation_id: str, user_id: Optional[str] = None
    ) -> Optional[Dict]:
        """Load and return a single conversation, or None if missing/invalid.

        Args:
            conversation_id: Conversation ID
            user_id: User client ID (required for postgres/redis mode)

        Returns:
            Conversation dict or None
        """
        if self.mode == "local":
            return self.backend.get_conversation(conversation_id)

        elif self.mode == "postgres":
            if not user_id:
                raise ValueError("user_id is required for postgres mode")
            return self.backend.get_conversation(conversation_id, user_id)

        elif self.mode == "redis":
            if not user_id:
                raise ValueError("user_id is required for redis mode")

            # Try cache first
            if self.cache and self.cache.is_available():
                cached = self.cache.get_conversation_messages(conversation_id, user_id)
                if cached is not None:
                    return cached

                # Cache miss
                logger.info(f"Cache miss for conversation {conversation_id}")

            # Load from PostgreSQL
            conversation = self.backend.get_conversation(conversation_id, user_id)

            # Populate cache
            if conversation and self.cache and self.cache.is_available():
                self.cache.set_conversation_messages(conversation_id, conversation['messages'])

            return conversation

        else:
            raise NotImplementedError(f"Mode {self.mode} not implemented")

    def save_conversation(
        self, conversation_id: str, conversation: Dict, user_id: Optional[str] = None
    ) -> None:
        """Persist a conversation atomically to storage.

        Args:
            conversation_id: Conversation ID
            conversation: Conversation dict
            user_id: User client ID (required for postgres/redis mode)
        """
        if self.mode == "local":
            self.backend.save_conversation(conversation_id, conversation)

        elif self.mode == "postgres":
            if not user_id:
                raise ValueError("user_id is required for postgres mode")
            self.backend.save_conversation(conversation_id, user_id, conversation)

        elif self.mode == "redis":
            if not user_id:
                raise ValueError("user_id is required for redis mode")

            # 1. Write to PostgreSQL first (source of truth)
            self.backend.save_conversation(conversation_id, user_id, conversation)

            # 2. Update Redis cache
            if self.cache and self.cache.is_available():
                # Update conversation metadata (for conversation list)
                self.cache.update_conversation_metadata(user_id, conversation_id, conversation)

                # Append new messages (efficient)
                # Check how many messages are already cached
                try:
                    redis_msg_count = self.cache.redis_client.llen(f"chat:{conversation_id}:messages") or 0
                    new_messages = conversation['messages'][redis_msg_count:]
                    if new_messages:
                        # Append with correct sequence numbering
                        self.cache.append_messages(conversation_id, new_messages, start_sequence=redis_msg_count)
                    elif redis_msg_count == 0:
                        # No messages cached yet, cache all
                        self.cache.set_conversation_messages(conversation_id, conversation['messages'])
                except Exception as e:
                    logger.warning(f"Failed to append messages to cache: {e}")

        else:
            raise NotImplementedError(f"Mode {self.mode} not implemented")

    def delete_conversation(
        self, conversation_id: str, user_id: Optional[str] = None
    ) -> None:
        """Remove a conversation from storage if it exists.

        Args:
            conversation_id: Conversation ID
            user_id: User client ID (required for postgres/redis mode)
        """
        if self.mode == "local":
            self.backend.delete_conversation(conversation_id)

        elif self.mode == "postgres":
            if not user_id:
                raise ValueError("user_id is required for postgres mode")
            self.backend.delete_conversation(conversation_id, user_id)

        elif self.mode == "redis":
            if not user_id:
                raise ValueError("user_id is required for redis mode")

            # 1. Delete from PostgreSQL first
            self.backend.delete_conversation(conversation_id, user_id)

            # 2. Invalidate cache
            if self.cache and self.cache.is_available():
                self.cache.delete_conversation_cache(user_id, conversation_id)

        else:
            raise NotImplementedError(f"Mode {self.mode} not implemented")

    def close(self) -> None:
        """Close any open connections (postgres/redis mode only)."""
        if self.backend and hasattr(self.backend, 'close'):
            self.backend.close()
        if self.cache and hasattr(self.cache, 'close'):
            self.cache.close()
