"""
Local JSON-backed database that mimics the Supabase Python client's query-builder interface.

Usage:
    from local_db import LocalDB
    db = LocalDB("local_data")          # stores one .json per table in local_data/
    db.table("trades").insert({...}).execute()
    rows = db.table("trades").select("*").eq("strategy_id", "A_M1").execute()

Toggle back to Supabase by changing STORAGE_MODE in api.py.
"""

import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime


class _Result:
    """Mimics the Supabase APIResponse — .data holds the list of rows."""
    __slots__ = ("data",)

    def __init__(self, data):
        self.data = data


class _TableQuery:
    """Chainable query builder that mirrors the supabase-py PostgREST interface."""

    def __init__(self, store: "_TableStore"):
        self._store = store
        self._op = "select"           # select | insert | update | upsert | delete
        self._columns = "*"
        self._filters: list[tuple] = []   # (op, col, val)
        self._order_col = None
        self._order_desc = False
        self._limit_n = None
        self._single = False
        self._payload = None
        self._on_conflict = None

    # ── operation starters ───────────────────────────────────────────────────
    def select(self, columns: str = "*"):
        self._op = "select"
        self._columns = columns
        return self

    def insert(self, data):
        self._op = "insert"
        self._payload = data if isinstance(data, list) else [data]
        return self

    def update(self, data: dict):
        self._op = "update"
        self._payload = data
        return self

    def upsert(self, data, on_conflict: str = "id"):
        self._op = "upsert"
        self._payload = data if isinstance(data, list) else [data]
        self._on_conflict = on_conflict
        return self

    def delete(self):
        self._op = "delete"
        return self

    # ── filters ──────────────────────────────────────────────────────────────
    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def neq(self, col, val):
        self._filters.append(("neq", col, val))
        return self

    def gte(self, col, val):
        self._filters.append(("gte", col, val))
        return self

    def lte(self, col, val):
        self._filters.append(("lte", col, val))
        return self

    def gt(self, col, val):
        self._filters.append(("gt", col, val))
        return self

    def lt(self, col, val):
        self._filters.append(("lt", col, val))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, vals))
        return self

    # ── modifiers ────────────────────────────────────────────────────────────
    def order(self, col, desc=False):
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n):
        self._limit_n = n
        return self

    def single(self):
        self._single = True
        return self

    # ── execute ──────────────────────────────────────────────────────────────
    def execute(self):
        if self._op == "select":
            return self._exec_select()
        elif self._op == "insert":
            return self._exec_insert()
        elif self._op == "update":
            return self._exec_update()
        elif self._op == "upsert":
            return self._exec_upsert()
        elif self._op == "delete":
            return self._exec_delete()
        return _Result([])

    # ── internals ────────────────────────────────────────────────────────────
    def _match(self, row: dict) -> bool:
        for op, col, val in self._filters:
            rv = row.get(col)
            if op == "eq" and rv != val:
                return False
            if op == "neq" and rv == val:
                return False
            if op == "gte":
                if rv is None:
                    return False
                if str(rv) < str(val):
                    return False
            if op == "lte":
                if rv is None:
                    return False
                if str(rv) > str(val):
                    return False
            if op == "gt":
                if rv is None:
                    return False
                if str(rv) <= str(val):
                    return False
            if op == "lt":
                if rv is None:
                    return False
                if str(rv) >= str(val):
                    return False
            if op == "in" and rv not in val:
                return False
        return True

    def _project(self, row: dict) -> dict:
        if self._columns == "*":
            return deepcopy(row)
        cols = [c.strip() for c in self._columns.split(",")]
        return {c: row.get(c) for c in cols}

    def _exec_select(self):
        try:
            rows = self._store.read()
        except RuntimeError:
            # Read failed (e.g. mid-write from another process). Return empty
            # instead of raising to keep dashboard responsive. No data is
            # overwritten because this is a pure read.
            rows = []
        matched = [self._project(r) for r in rows if self._match(r)]
        if self._order_col:
            matched.sort(
                key=lambda r: r.get(self._order_col) or "",
                reverse=self._order_desc,
            )
        if self._limit_n is not None:
            matched = matched[: self._limit_n]
        if self._single:
            return _Result(matched[0] if matched else None)
        return _Result(matched)

    def _exec_insert(self):
        # If the current file can't be read, refuse the write — otherwise
        # we'd replace the (still-valid) on-disk rows with just our payload.
        rows = self._store.read()
        for item in self._payload:
            item = deepcopy(item)
            if "id" not in item:
                item["id"] = str(uuid.uuid4())
            if "created_at" not in item:
                item["created_at"] = datetime.utcnow().isoformat()
            rows.append(item)
        self._store.write(rows)
        return _Result(self._payload)

    def _exec_update(self):
        rows = self._store.read()
        updated = []
        for r in rows:
            if self._match(r):
                r.update(self._payload)
                updated.append(deepcopy(r))
        self._store.write(rows)
        return _Result(updated)

    def _exec_upsert(self):
        rows = self._store.read()
        conflict_col = self._on_conflict or "id"
        existing_keys = {r.get(conflict_col): i for i, r in enumerate(rows)}
        result = []
        for item in self._payload:
            item = deepcopy(item)
            key = item.get(conflict_col)
            if key is not None and key in existing_keys:
                idx = existing_keys[key]
                rows[idx].update(item)
                result.append(deepcopy(rows[idx]))
            else:
                if "id" not in item:
                    item["id"] = str(uuid.uuid4())
                if "created_at" not in item:
                    item["created_at"] = datetime.utcnow().isoformat()
                rows.append(item)
                existing_keys[item.get(conflict_col)] = len(rows) - 1
                result.append(deepcopy(item))
        self._store.write(rows)
        return _Result(result)

    def _exec_delete(self):
        rows = self._store.read()
        to_delete = [r for r in rows if self._match(r)]
        remaining = [r for r in rows if not self._match(r)]
        self._store.write(remaining)
        return _Result(to_delete)


class _TableStore:
    """
    Cross-process JSON file store for a single table.

    Safety guarantees:
    - Atomic writes: write to <file>.tmp then os.replace() → readers never see a
      half-written file. os.replace is atomic on Windows + POSIX.
    - Retry-on-decode: if a read catches a mid-write (partial JSON), retry a few
      times with small backoff before giving up. Critically we RAISE on persistent
      decode failure instead of silently returning [] — the old behavior would
      cause subsequent UPDATE/INSERT to overwrite good data with an empty list.
    - Cross-process lock file: advisory file lock serializes writes from both
      the scanner process and the api.py process writing to the same JSON.
    """

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()          # in-process lock
        self._lock_path = path + ".lock"        # cross-process lock file

    # ── cross-process file lock (msvcrt on Windows, fcntl on POSIX) ─────────
    def _xplock_acquire(self):
        fh = open(self._lock_path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                # Lock 1 byte; blocks until available
                while True:
                    try:
                        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                        break
                    except OSError:
                        # Retry briefly on transient Windows lock errors
                        import time as _t
                        _t.sleep(0.01)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            fh.close()
            return None
        return fh

    def _xplock_release(self, fh):
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()

    def read(self) -> list[dict]:
        with self._lock:
            if not os.path.exists(self._path):
                return []
            # Retry up to ~100ms in case we caught a mid-write
            last_err = None
            for attempt in range(10):
                try:
                    with open(self._path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return data if isinstance(data, list) else []
                except json.JSONDecodeError as e:
                    last_err = e
                    import time as _t
                    _t.sleep(0.01)
                except IOError as e:
                    last_err = e
                    import time as _t
                    _t.sleep(0.01)
            # Persistent failure — DO NOT return [] (that would let a later
            # write overwrite the file with an empty list). Bubble it up so
            # the caller sees the error and skips the update.
            raise RuntimeError(
                f"Failed to read {self._path} after retries: {last_err}"
            )

    def write(self, rows: list[dict]):
        """Atomic write: write to <path>.tmp then os.replace()."""
        with self._lock:
            fh = self._xplock_acquire()
            try:
                tmp_path = self._path + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(rows, f, indent=2, default=str)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except (OSError, AttributeError):
                        pass
                # Atomic on both Windows and POSIX
                os.replace(tmp_path, self._path)
            finally:
                self._xplock_release(fh)

    def clear(self):
        self.write([])


class LocalDB:
    """
    Drop-in replacement for the Supabase client used by api.py.

    Only implements the subset of the PostgREST query builder that api.py actually uses.
    Data is persisted as JSON files in `data_dir/` (one file per table).
    """

    def __init__(self, data_dir: str = "local_data"):
        self._data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._stores: dict[str, _TableStore] = {}
        self._lock = threading.Lock()
        self._seed_defaults()

    def table(self, name: str) -> _TableQuery:
        store = self._get_store(name)
        return _TableQuery(store)

    def _get_store(self, name: str) -> _TableStore:
        with self._lock:
            if name not in self._stores:
                path = os.path.join(self._data_dir, f"{name}.json")
                self._stores[name] = _TableStore(path)
            return self._stores[name]

    def reset_all(self):
        """Prune ALL local data — called by reset-allocate."""
        with self._lock:
            for store in self._stores.values():
                store.clear()
            # Also clear any files on disk not yet loaded
            for fname in os.listdir(self._data_dir):
                if fname.endswith(".json"):
                    path = os.path.join(self._data_dir, fname)
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump([], f)
        # Re-seed defaults after reset
        self._seed_defaults()

    def reset_table(self, table_name: str):
        """Prune a single table."""
        store = self._get_store(table_name)
        store.clear()

    def _seed_defaults(self):
        """Seed tables with sensible defaults so the dashboard isn't empty on first load."""
        now = datetime.utcnow().isoformat()

        # nodes — must match scanner's NODE_ID
        nodes_store = self._get_store("nodes")
        if not nodes_store.read():
            nodes_store.write([{
                "node_id": "singapore-01",
                "name": "Node 1 — Singapore",
                "region": "Singapore",
                "status": "running",
                "last_heartbeat": now,
            }])

        # deployment_config
        dc_store = self._get_store("deployment_config")
        if not dc_store.read():
            dc_store.write([
                {"key": "global_regime", "value": "NORMAL"},
                {"key": "kill_switch_global", "value": "false"},
            ])

        # strategy_plugins — A_M1, A_CEX, A_M2
        sp_store = self._get_store("strategy_plugins")
        if not sp_store.read():
            sp_store.write([
                {
                    "strategy_id": "A_M1_triangular_arb",
                    "display_name": "Triangular Arb (A_M1)",
                    "category": "A_math",
                    "mode": "paper",
                    "version_tag": "v1",
                    "strategy_config": {},
                    "created_at": now,
                },
                {
                    "strategy_id": "A_CEX_cross_arb",
                    "display_name": "CEX Cross Arb (A_CEX)",
                    "category": "A_math",
                    "mode": "paper",
                    "version_tag": "v1",
                    "strategy_config": {},
                    "created_at": now,
                },
                {
                    "strategy_id": "A_M2_funding_rate",
                    "display_name": "Funding Rate (A_M2)",
                    "category": "A_math",
                    "mode": "paper",
                    "version_tag": "v1",
                    "strategy_config": {},
                    "created_at": now,
                },
            ])

        # strategy_flags — A_M1 enabled
        sf_store = self._get_store("strategy_flags")
        if not sf_store.read():
            sf_store.write([
                {
                    "strategy_id": "A_M1_triangular_arb",
                    "enabled": True,
                    "mode": "paper",
                    "max_capital": 10000.0,
                },
                {
                    "strategy_id": "A_CEX_cross_arb",
                    "enabled": True,
                    "mode": "paper",
                    "max_capital": 5000.0,
                },
                {
                    "strategy_id": "A_M2_funding_rate",
                    "enabled": False,
                    "mode": "paper",
                    "max_capital": 5000.0,
                },
            ])
