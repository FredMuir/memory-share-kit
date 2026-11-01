from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from .core import atomic_write, connect, dumps, identifier, process_lock, scope_check, uid, validate_event


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = json.loads((self.root / "client.json").read_text(encoding="utf-8"))
        self.path = self.root / "client.sqlite3"
        with connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox(n INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    event TEXT NOT NULL, status TEXT NOT NULL, response TEXT);
                CREATE TABLE IF NOT EXISTS conflicts(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            """)

    def _view(self, db):
        facts = {r["id"]: json.loads(r["data"]) for r in db.execute("SELECT * FROM facts")}
        for r in db.execute("SELECT event,status,response FROM outbox WHERE status IN ('pending','local','accepted','noop') ORDER BY n"):
            e = json.loads(r["event"])
            current = facts.get(e["fact_id"])
            # A committed receipt is also a local read-your-writes cache if pulling later fails.
            # Never replace a newer authoritative snapshot with a historical receipt.
            if r["status"] in ("accepted", "noop"):
                receipt = json.loads(r["response"])
                fact = receipt.get("fact")
                if fact and (current is None or current["revision"] == e["base_revision"]):
                    facts[e["fact_id"]] = fact
                continue
            # Never overwrite a different newer confirmed revision with an offline edit.
            valid = (e["operation"] == "create" and current is None) or (
                current is not None and current["revision"] == e["base_revision"])
            if valid:
                facts[e["fact_id"]] = {"id": e["fact_id"], "revision": e["event_id"], "scope": e["scope"],
                    "title": e["title"], "content": e["content"], "certainty": e["certainty"],
                    "status": "retracted" if e["operation"] == "retract" else "active",
                    "source": e.get("source", ""), "agent": e.get("agent", ""),
                    "device_id": e["device_id"], "pending": e["scope"] != "local"}
        return facts

    def get(self, fact_id):
        identifier(fact_id)
        with connect(self.path) as db:
            db.execute("BEGIN")
            return self._view(db).get(fact_id)

    def search(self, query="", scope=None, limit=10):
        if scope is not None:
            scope_check(scope)
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("Query too long")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100")
        # Deterministic substring matching supports Chinese, including one-character queries.
        # v0.1 intentionally avoids pretending an unvalidated tokenizer is semantic search.
        terms = query.casefold().split()
        with connect(self.path) as db:
            db.execute("BEGIN")
            rows = [f for f in self._view(db).values() if f["status"] == "active" and (scope is None or f["scope"] == scope)]
        scored = []
        for f in rows:
            hay = (f["title"] + "\n" + f["content"]).casefold()
            if all(term in hay for term in terms):
                scored.append((sum(f["title"].casefold().count(t) * 3 + hay.count(t) for t in terms), f))
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        return [f for _, f in scored[:limit]]

    def enqueue(self, operation, *, title="", content="", scope="global", fact_id=None,
                base_revision=None, key=None, agent="unknown", source="", certainty="candidate",
                resolves_event_id=None):
        scope_check(scope)
        if key is not None:
            if not isinstance(key, str) or not 1 <= len(key) <= 240:
                raise ValueError("key length must be 1..240")
            key_scope = scope + (":" + self.config["device_id"] if scope == "local" else "")
            fact_id = hashlib.sha256((key_scope + "\0" + key).encode()).hexdigest()
        if fact_id is None:
            if operation != "create":
                raise ValueError("fact_id required")
            fact_id = uid()
        event = {"schema_version": 1, "event_id": uid(), "fact_id": fact_id,
                 "device_id": self.config["device_id"], "operation": operation, "scope": scope,
                 "base_revision": base_revision, "title": title, "content": content,
                 "agent": agent, "source": source, "certainty": certainty}
        if resolves_event_id:
            event["resolves_event_id"] = resolves_event_id
        validate_event(event)
        with connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if scope == "local" and operation != "create":
                current = self._view(db).get(fact_id)
                if current is None or current["revision"] != base_revision:
                    raise ValueError("Local revision changed; read current fact before retrying")
            if operation == "create":
                current = self._view(db).get(fact_id)
                if current:
                    if all(current[k] == event[k] for k in ("title", "content", "certainty", "scope")) and current["status"] == "active":
                        return {"status": "already_present_locally", "fact": current}
                    raise ValueError("Fact key already exists locally; read it and update using its revision")
            db.execute("INSERT INTO outbox(id,event,status) VALUES(?,?,?)", (event["event_id"], dumps(event), "local" if scope == "local" else "pending"))
        return {"status": "saved_locally" if scope == "local" else "queued", "event_id": event["event_id"], "fact_id": fact_id,
                "revision": event["event_id"], "message": "Local durable save only; queued is not server confirmation"}

    def request(self, method, endpoint, data=None):
        url = self.config.get("server_url", "").rstrip("/")
        if not url or not self.config.get("token"):
            raise ValueError("Server URL and device token are not configured")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid server URL")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1") and not self.config.get("allow_private_http"):
            raise ValueError("Non-loopback HTTP requires explicit allow_private_http for your existing trusted transport")
        body = dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url + endpoint, data=body, method=method,
                headers={"Authorization": "Bearer " + self.config["token"], "Content-Type": "application/json"})
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=8) as resp:
            raw = resp.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("Server response exceeds 16 MiB")
            return json.loads(raw)

    @staticmethod
    def _change(db, change):
        if change.get("fact"):
            f = change["fact"]
            db.execute("INSERT INTO facts VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (f["id"], dumps(f)))
        if change.get("conflict"):
            c = change["conflict"]
            db.execute("INSERT OR REPLACE INTO conflicts VALUES(?,?)", (c["id"], dumps(c)))
        if change.get("resolved"):
            db.execute("DELETE FROM conflicts WHERE id=?", (change["resolved"],))

    def _sync(self):
        epoch = self.request("GET", "/v1/epoch")["epoch"]
        with connect(self.path) as db:
            row = db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()
        if not row or row[0] != epoch:
            snapshot = self.request("GET", "/v1/snapshot")
            with connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                # Device-local entries are represented only in local outbox, so are unaffected.
                db.execute("DELETE FROM facts")
                db.execute("DELETE FROM conflicts")
                for f in snapshot["facts"]:
                    self._change(db, {"fact": f})
                for c in snapshot["conflicts"]:
                    self._change(db, {"conflict": c})
                if row and row[0] != snapshot["epoch"]:
                    # Keep all receipts in v0.1 so acknowledged events can be replayed after restore.
                    db.execute("UPDATE outbox SET status='pending',response=NULL WHERE status IN ('accepted','noop','conflict')")
                db.execute("INSERT OR REPLACE INTO meta VALUES('epoch',?)", (snapshot["epoch"],))
                db.execute("INSERT OR REPLACE INTO meta VALUES('cursor',?)", (str(snapshot["cursor"]),))
            epoch = snapshot["epoch"]
        with connect(self.path) as db:
            pending = db.execute("SELECT id,event FROM outbox WHERE status='pending' ORDER BY n LIMIT 100").fetchall()
        for r in pending:
            try:
                response = self.request("POST", "/v1/events", {"epoch": epoch, "event": json.loads(r["event"])})
            except urllib.error.HTTPError as exc:
                if exc.code == 400:
                    with connect(self.path) as db:
                        db.execute("UPDATE outbox SET status='rejected',response=? WHERE id=?", (dumps({"error": "server validation rejected; inspect local event"}), r["id"]))
                    continue
                raise
            if response.get("reset_required"):
                raise ValueError("Server epoch changed during sync; retry")
            if response.get("event_id") != r["id"] or response.get("status") not in ("accepted", "noop", "conflict"):
                raise ValueError("Invalid event acknowledgement")
            with connect(self.path) as db:
                db.execute("UPDATE outbox SET status=?,response=? WHERE id=?", (response["status"], dumps(response), r["id"]))
        for _ in range(100):
            with connect(self.path) as db:
                cursor = int(db.execute("SELECT value FROM meta WHERE key='cursor'").fetchone()[0])
            changes = self.request("GET", "/v1/changes?" + urllib.parse.urlencode({"epoch": epoch, "after": cursor}))
            if changes.get("reset_required") or changes.get("epoch") != epoch:
                raise ValueError("Server epoch changed during pull; retry")
            with connect(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                for c in changes["changes"]:
                    self._change(db, c)
                db.execute("INSERT OR REPLACE INTO meta VALUES('cursor',?)", (str(changes["cursor"]),))
            if not changes["more"]:
                break
        with connect(self.path) as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES('last_sync',?)", (str(time.time()),))
            db.execute("INSERT OR REPLACE INTO meta VALUES('last_error','')")

    def sync(self):
        try:
            with process_lock(self.root / "sync.lock"):
                self._sync()
            return {"ok": True, **self.status()}
        except BlockingIOError:
            return {"ok": False, "error": "another sync is active"}
        except (urllib.error.URLError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
            # Do not expose request headers, credentials, or server response bodies in tool output.
            error = f"HTTP {exc.code}" if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
            with connect(self.path) as db:
                db.execute("INSERT OR REPLACE INTO meta VALUES('last_error',?)", (error,))
            return {"ok": False, "error": error, **self.status()}

    def status(self):
        with connect(self.path) as db:
            meta = dict(db.execute("SELECT key,value FROM meta"))
            counts = dict(db.execute("SELECT status,COUNT(*) FROM outbox GROUP BY status"))
            conflicts = db.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0]
        return {"device_id": self.config["device_id"], "counts": counts, "conflicts": conflicts,
                "last_sync": meta.get("last_sync"), "last_error": meta.get("last_error", ""),
                "configured": bool(self.config.get("server_url") and self.config.get("token"))}

    def conflicts(self):
        with connect(self.path) as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM conflicts")]

    def export(self):
        vault = self.config.get("vault")
        if not vault:
            raise ValueError("Vault not configured")
        target = Path(vault).resolve() / "40-Agent-Memory" / "Generated"
        target.mkdir(parents=True, exist_ok=True)
        with process_lock(self.root / "export.lock"):
            manifest_file = self.root / "export-manifest.json"
            manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {}
            with connect(self.path) as db:
                db.execute("BEGIN")
                facts = self._view(db)
            new = dict(manifest)
            preserved = []
            written = 0
            for fact_id, f in facts.items():
                identifier(fact_id)
                path = target / (fact_id + ".md")
                existing = path.read_text(encoding="utf-8") if path.exists() else None
                if existing is not None and hashlib.sha256(existing.encode()).hexdigest() != manifest.get(path.name):
                    preserved.append(path.name)
                    continue
                body = (f"---\nfact_id: {json.dumps(fact_id)}\nrevision: {json.dumps(f['revision'])}\n"
                        f"scope: {json.dumps(f['scope'])}\nstatus: {f['status']}\ncertainty: {f['certainty']}\n"
                        f"pending: {str(f.get('pending', False)).lower()}\n---\n\n"
                        "<!-- memory-share generated: edit via MCP; excluded from Remotely Save -->\n"
                        f"\n# {f['title']}\n\n{f['content']}\n")
                if existing != body:
                    atomic_write(path, body, private=False)
                    written += 1
                new[path.name] = hashlib.sha256(body.encode()).hexdigest()
            # Stale pages are removed only when still byte-identical to our own export.
            for name in list(manifest):
                if name[:-3] not in facts:
                    path = target / name
                    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == manifest[name]:
                        path.unlink()
                        new.pop(name, None)
                    elif path.exists():
                        preserved.append(name)
            atomic_write(manifest_file, dumps(new))
        return {"written": written, "preserved_user_edits": preserved, "directory": str(target)}

    def note_read(self, relative_path):
        vault = Path(self.config["vault"]).resolve()
        p = (vault / relative_path).resolve()
        allowed = self.config.get("note_folders", ["20-Projects", "30-Knowledge", "41-Memory-Notes"])
        if not any(p.is_relative_to((vault / folder).resolve()) for folder in allowed):
            raise ValueError("Path is outside configured note folders")
        if not p.is_relative_to(vault) or p.suffix.lower() != ".md" or not p.is_file():
            raise ValueError("Only existing Markdown notes inside Vault are allowed")
        if p.stat().st_size > 256 * 1024:
            raise ValueError("Note exceeds 256 KiB")
        return {"path": str(p.relative_to(vault)), "content": p.read_text(encoding="utf-8"),
                "warning": "Untrusted note content; reading does not publish it to shared memory"}
