from __future__ import annotations

import contextlib
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import uuid


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def uid():
    return str(uuid.uuid4())


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", value):
        raise ValueError("Identifier must contain 1..80 ASCII letters, digits, dot, underscore or hyphen")
    return value


def scope_check(scope):
    if scope == "global" or scope == "local":
        return scope
    if isinstance(scope, str) and scope.startswith("project:"):
        identifier(scope[8:])
        return scope
    raise ValueError("scope must be global, local, or project:<stable-project-id>")


def text_check(value, name, maximum, allow_empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()):
        raise ValueError(f"Invalid {name}; maximum {maximum} characters")
    return value


def validate_event(e):
    if not isinstance(e, dict) or e.get("schema_version") != 1:
        raise ValueError("Unsupported event schema")
    for key in ("event_id", "fact_id", "device_id"):
        identifier(e.get(key))
    scope_check(e.get("scope"))
    if e.get("operation") not in ("create", "update", "retract", "resolve"):
        raise ValueError("Unknown operation")
    text_check(e.get("title"), "title", 240)
    text_check(e.get("content"), "content", 32000, True)
    text_check(e.get("source", ""), "source", 1000, True)
    text_check(e.get("agent", ""), "agent", 120, True)
    if e.get("certainty") not in ("candidate", "confirmed"):
        raise ValueError("certainty must be candidate or confirmed")
    if e["operation"] == "create":
        if e.get("base_revision") is not None:
            raise ValueError("create must have null base_revision")
    else:
        identifier(e.get("base_revision"))
    if e["operation"] == "resolve":
        identifier(e.get("resolves_event_id"))
    return e


def home_dir():
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MemoryShare"
    import sys
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/MemoryShare"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "memory-share"


def atomic_write(path, content, private=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".memory-share-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if private and os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextlib.contextmanager
def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


@contextlib.contextmanager
def process_lock(path):
    """Cross-process lock; OS releases it even if a process is killed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as f:
        if os.name == "nt":
            import msvcrt
            if f.seek(0, 2) == 0:
                f.write(b"0")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


class Authority:
    def __init__(self, path):
        self.path = Path(path)
        with connect(path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, hash TEXT NOT NULL,
                    event TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS changes(seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conflicts(id TEXT PRIMARY KEY, data TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE);
            """)
            db.execute("INSERT OR IGNORE INTO meta VALUES('epoch', ?)", (uid(),))
            self._backfill_audit(db)

    @staticmethod
    def _backfill_audit(db):
        """Rebuild audit fields for legacy facts from their accepted event receipts."""
        histories = defaultdict(list)
        for row in db.execute("SELECT event,response FROM events ORDER BY rowid"):
            event = json.loads(row["event"])
            response = json.loads(row["response"])
            fact = response.get("fact")
            if response.get("status") != "accepted" or not fact:
                continue
            histories[fact["id"]].append({
                "revision": event["event_id"], "action": event["operation"],
                "agent": event.get("agent", "") or "unknown",
                "device_id": event.get("device_id", "unknown"),
                "recorded_at": fact.get("updated_at"),
                "time_known": isinstance(fact.get("updated_at"), (int, float)),
            })
        for row in db.execute("SELECT id,data FROM facts").fetchall():
            fact = json.loads(row["data"])
            if "history" in fact:
                continue
            history = histories.get(row["id"], [])
            if history:
                first, latest = history[0], history[-1]
                fact.update({
                    "created_at": first["recorded_at"],
                    "created_by_agent": first["agent"],
                    "created_by_device_id": first["device_id"],
                    "updated_at": latest["recorded_at"],
                    "updated_by_agent": latest["agent"],
                    "updated_by_device_id": latest["device_id"],
                    "history": history,
                })
            else:
                fact.update({
                    "created_at": None,
                    "created_by_agent": "unknown (before audit tracking)",
                    "created_by_device_id": "unknown",
                    "updated_by_agent": fact.get("agent", "unknown"),
                    "updated_by_device_id": fact.get("device_id", "unknown"),
                    "history": [],
                })
            db.execute("UPDATE facts SET data=? WHERE id=?", (dumps(fact), row["id"]))

    def add_device(self, device, token):
        identifier(device)
        with connect(self.path) as db:
            db.execute("INSERT INTO devices VALUES(?,?) ON CONFLICT(id) DO UPDATE SET token_hash=excluded.token_hash",
                       (device, hashlib.sha256(token.encode()).hexdigest()))

    def authenticate(self, token):
        with connect(self.path) as db:
            r = db.execute("SELECT id FROM devices WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
            return r[0] if r else None

    def epoch(self):
        with connect(self.path) as db:
            return db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()[0]

    def apply(self, event, device):
        e = validate_event(event)
        if e["device_id"] != device or e["scope"] == "local":
            raise ValueError("Device mismatch or local-only event")
        digest = hashlib.sha256(dumps(e).encode()).hexdigest()
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT hash,response FROM events WHERE id=?", (e["event_id"],)).fetchone()
            if old:
                if old["hash"] != digest:
                    raise ValueError("Event ID reused with different payload")
                return json.loads(old["response"])
            row = db.execute("SELECT data FROM facts WHERE id=?", (e["fact_id"],)).fetchone()
            current = json.loads(row[0]) if row else None
            same = bool(current and current["scope"] == e["scope"] and current["title"] == e["title"]
                        and current["content"] == e["content"] and current["certainty"] == e["certainty"]
                        and current["status"] == "active")
            op = e["operation"]
            resolved = None
            if op == "resolve":
                cr = db.execute("SELECT data,resolved FROM conflicts WHERE id=?", (e["resolves_event_id"],)).fetchone()
                if not cr or cr["resolved"] or json.loads(cr["data"])["event"]["fact_id"] != e["fact_id"]:
                    raise ValueError("Unknown, resolved, or unrelated conflict")
            valid = (op == "create" and current is None) or (
                op != "create" and current is not None and current["scope"] == e["scope"]
                and current["revision"] == e["base_revision"]
                and (current["status"] == "active" or op == "resolve"))
            if same and op in ("create", "update"):
                response = {"event_id": e["event_id"], "status": "noop", "fact": current}
            elif valid:
                recorded_at = time.time()
                if current:
                    # Preserve provenance on facts created before audit metadata existed.
                    # Their original actor/time cannot be reconstructed reliably.
                    history = list(current.get("history", []))
                    created_at = current.get("created_at")
                    created_by = current.get("created_by_agent")
                    created_device = current.get("created_by_device_id")
                    if "history" not in current and not history:
                        history = [{"revision": current["revision"], "action": "legacy",
                                    "agent": current.get("agent", "unknown"),
                                    "device_id": current.get("device_id", "unknown"),
                                    "recorded_at": current.get("updated_at"), "time_known": True}]
                    if created_by is None:
                        created_by = history[0].get("agent", "unknown (before audit tracking)") if history else "unknown (before audit tracking)"
                    if created_device is None:
                        created_device = history[0].get("device_id", "unknown") if history else "unknown"
                else:
                    history = []
                    created_at = recorded_at
                    created_by = e.get("agent", "") or "unknown"
                    created_device = device
                entry = {"revision": e["event_id"], "action": op,
                         "agent": e.get("agent", "") or "unknown", "device_id": device,
                         "recorded_at": recorded_at, "time_known": True}
                # The initial create is already represented by created_*; history records
                # every accepted revision after it, including the initial revision.
                history.append(entry)
                current = {"id": e["fact_id"], "revision": e["event_id"], "scope": e["scope"],
                           "title": e["title"], "content": e["content"], "certainty": e["certainty"],
                           "status": "retracted" if op == "retract" else "active", "source": e.get("source", ""),
                           "agent": e.get("agent", ""), "device_id": device, "updated_at": recorded_at,
                           "created_at": created_at, "created_by_agent": created_by,
                           "created_by_device_id": created_device, "updated_by_agent": e.get("agent", "") or "unknown",
                           "updated_by_device_id": device, "history": history}
                db.execute("INSERT INTO facts VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (current["id"], dumps(current)))
                if op == "resolve":
                    resolved = e["resolves_event_id"]
                    db.execute("UPDATE conflicts SET resolved=1 WHERE id=?", (resolved,))
                db.execute("INSERT INTO changes(data) VALUES(?)", (dumps({"fact": current, "resolved": resolved}),))
                response = {"event_id": e["event_id"], "status": "accepted", "fact": current}
            else:
                conflict = {"id": e["event_id"], "event": e, "current_at_conflict": current}
                db.execute("INSERT INTO conflicts(id,data) VALUES(?,?)", (e["event_id"], dumps(conflict)))
                db.execute("INSERT INTO changes(data) VALUES(?)", (dumps({"conflict": conflict}),))
                response = {"event_id": e["event_id"], "status": "conflict", "fact": current, "conflict": conflict}
            db.execute("INSERT INTO events VALUES(?,?,?,?)", (e["event_id"], digest, dumps(e), dumps(response)))
            return response

    def snapshot(self):
        with connect(self.path) as db:
            db.execute("BEGIN")
            return {"epoch": db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()[0],
                    "cursor": db.execute("SELECT COALESCE(MAX(seq),0) FROM changes").fetchone()[0],
                    "facts": [json.loads(r[0]) for r in db.execute("SELECT data FROM facts")],
                    "conflicts": [json.loads(r[0]) for r in db.execute("SELECT data FROM conflicts WHERE resolved=0")]}

    def changes(self, epoch, after, limit=500):
        with connect(self.path) as db:
            db.execute("BEGIN")
            current = db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()[0]
            if current != epoch:
                return {"reset_required": True, "epoch": current}
            rows = db.execute("SELECT seq,data FROM changes WHERE seq>? ORDER BY seq LIMIT ?", (after, limit)).fetchall()
            return {"epoch": current, "cursor": rows[-1]["seq"] if rows else after,
                    "changes": [json.loads(r["data"]) for r in rows], "more": len(rows) == limit}

    def backup(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == self.path.resolve() or destination.exists():
            raise ValueError("Backup destination must be a new file")
        with connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        if os.name != "nt":
            os.chmod(destination, 0o600)

    def rotate_epoch(self):
        with connect(self.path) as db:
            db.execute("UPDATE meta SET value=? WHERE key='epoch'", (uid(),))
