"""Supabase client singleton. Always uses pooler port 6543."""
import os
from supabase import create_client, Client
from typing import Optional
import structlog

logger = structlog.get_logger()

_client: Optional[Client] = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")  # Use service key for backend
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _client = create_client(url, key)
    return _client


class SupabaseClient:
    """Thin wrapper. Use this class everywhere — never import raw supabase."""
    def __init__(self):
        self._client = get_supabase()

    def table(self, name: str):
        return self._client.table(name)

    async def heartbeat(self, node_id: str) -> None:
        """Update node heartbeat every 30 seconds."""
        try:
            from datetime import datetime
            self._client.table("nodes").update({
                "status": "online",
                "last_heartbeat": datetime.utcnow().isoformat(),
            }).eq("node_id", node_id).execute()
        except Exception as e:
            logger.warning("heartbeat_error", error=str(e))
