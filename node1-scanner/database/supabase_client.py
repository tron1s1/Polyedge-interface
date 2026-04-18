"""
Supabase client — with local JSON-backed fallback.

If STORAGE_MODE=local (default) OR Supabase env vars are missing,
this wraps LocalDB (../local_db.py) pointing at ../local_data/.
The dashboard API (api.py) reads from the same LocalDB, so trades
logged here show up on the dashboard immediately.

Set STORAGE_MODE=supabase + SUPABASE_URL + SUPABASE_SERVICE_KEY to
use the real Supabase backend.
"""
import os
import sys
from typing import Optional
import structlog

logger = structlog.get_logger()

_STORAGE_MODE = os.getenv("STORAGE_MODE", "local").lower()
_SUPA_URL = os.getenv("SUPABASE_URL")
_SUPA_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# Resolve ../local_data relative to this file (node1-scanner/database/ → Polyedge interface/)
_HERE = os.path.dirname(os.path.abspath(__file__))
_INTERFACE_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
_LOCAL_DATA_DIR = os.path.join(_INTERFACE_ROOT, "local_data")

_USE_LOCAL = _STORAGE_MODE == "local" or not (_SUPA_URL and _SUPA_KEY)

_client = None


def _get_local_db():
    """Import LocalDB from the interface root."""
    if _INTERFACE_ROOT not in sys.path:
        sys.path.insert(0, _INTERFACE_ROOT)
    from local_db import LocalDB
    return LocalDB(_LOCAL_DATA_DIR)


def get_supabase():
    global _client
    if _client is None:
        if _USE_LOCAL:
            logger.info("storage_mode_local", data_dir=_LOCAL_DATA_DIR)
            _client = _get_local_db()
        else:
            from supabase import create_client
            logger.info("storage_mode_supabase")
            _client = create_client(_SUPA_URL, _SUPA_KEY)
    return _client


class SupabaseClient:
    """
    Thin wrapper. Use this class everywhere — never import raw supabase.
    Transparently delegates to either Supabase or LocalDB based on STORAGE_MODE.
    """
    def __init__(self):
        self._client = get_supabase()
        self._is_local = _USE_LOCAL

    def table(self, name: str):
        return self._client.table(name)

    async def heartbeat(self, node_id: str) -> None:
        """Update node heartbeat every 30 seconds (non-blocking)."""
        import asyncio as _asyncio
        from datetime import datetime
        payload = {"status": "running", "last_heartbeat": datetime.utcnow().isoformat()}

        def _beat():
            try:
                self._client.table("nodes").update(payload).eq("node_id", node_id).execute()
            except Exception as e:
                logger.warning("heartbeat_error", error=str(e))

        try:
            _asyncio.get_event_loop().run_in_executor(None, _beat)
        except RuntimeError:
            _beat()
