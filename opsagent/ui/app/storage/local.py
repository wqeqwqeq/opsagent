"""Local JSON file storage backend for chat history."""
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


class LocalBackend:
    """Local JSON file storage backend.

    Stores each conversation as a separate JSON file in .chat_history/ directory.
    """

    def __init__(self, base_dir: Path) -> None:
        """Initialize local backend.

        Args:
            base_dir: Directory to store JSON files (typically .chat_history/)
        """
        self.store_dir = base_dir
        self._ensure_dir(self.store_dir)

    def list_conversations(self) -> List[Tuple[str, Dict]]:
        """Return list of (conversation_id, conversation_dict) from local storage.

        Returns:
            List of (conversation_id, conversation_dict) tuples
        """
        conversations: List[Tuple[str, Dict]] = []
        for path in sorted(self._iter_json_files(self.store_dir)):
            cid = path.stem
            data = self._safe_read_json(path)
            if data is not None:
                conversations.append((cid, data))
        return conversations

    def get_conversation(self, conversation_id: str) -> Optional[Dict]:
        """Load and return a single conversation, or None if missing/invalid.

        Args:
            conversation_id: Conversation ID

        Returns:
            Conversation dict or None
        """
        path = self.store_dir / f"{conversation_id}.json"
        return self._safe_read_json(path)

    def save_conversation(self, conversation_id: str, conversation: Dict) -> None:
        """Persist a conversation atomically to storage.

        Args:
            conversation_id: Conversation ID
            conversation: Conversation dict
        """
        path = self.store_dir / f"{conversation_id}.json"
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(conversation, ensure_ascii=False, indent=2))
        os.replace(tmp_path, path)

    def delete_conversation(self, conversation_id: str) -> None:
        """Remove a conversation from storage if it exists.

        Args:
            conversation_id: Conversation ID
        """
        path = self.store_dir / f"{conversation_id}.json"
        try:
            path.unlink(missing_ok=True)
        except TypeError:
            # Python <3.8 compatibility: ignore if file doesn't exist
            if path.exists():
                path.unlink()

    def close(self) -> None:
        """Close backend (no-op for local storage)."""
        pass

    # ------------------------------
    # Internal helpers
    # ------------------------------
    @staticmethod
    def _ensure_dir(path: Path) -> None:
        """Ensure directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _iter_json_files(directory: Path) -> Iterable[Path]:
        """Iterate over JSON files in directory."""
        if not directory.exists():
            return []
        return (p for p in directory.glob("*.json") if p.is_file())

    @staticmethod
    def _safe_read_json(path: Path) -> Optional[Dict]:
        """Safely read JSON file, returning None on error."""
        try:
            if not path.exists():
                return None
            return json.loads(path.read_text())
        except Exception:
            # Corrupt or unreadable file: ignore
            return None
