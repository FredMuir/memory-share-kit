from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from .core import atomic_write, connect, dumps, identifier, process_lock, scope_check, uid, validate_event


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _export_filename(title, fact_id):
    """Return a readable Obsidian filename with the stable machine ID retained."""
    identifier(fact_id)
    title = " ".join(str(title or "").split())
    slug = unicodedata.normalize("NFKC", title)
    slug = re.sub(r"[\s/\\<>:\"|?*#\[\]{}]+", "-", slug)
    slug = re.sub(r"[^\w.-]+", "-", slug, flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip(" .-_")
    if not slug:
        slug = "shared-memory"
    # Keep the full name under common 255-byte filesystem limits, including long IDs.
    while len(slug.encode("utf-8")) > 170:
        slug = slug[:-1]
    slug = slug.rstrip(" .-_") or "shared-memory"
    return f"{slug}--{fact_id}.md"


def _export_fact_id(filename):
    """Read IDs from both legacy `<id>.md` and readable `<title>--<id>.md` names."""
    stem = Path(filename).stem
    candidate = stem.rsplit("--", 1)[-1] if "--" in stem else stem
    try:
        return identifier(candidate)
    except ValueError:
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
                fact = {**(current or {}), "id": e["fact_id"], "revision": e["event_id"], "scope": e["scope"],
                    "title": e["title"], "content": e["content"], "certainty": e["certainty"],
                    "status": "retracted" if e["operation"] == "retract" else "active",
                    "source": e.get("source", ""), "agent": e.get("agent", ""),
                    "device_id": e["device_id"], "pending": e["scope"] != "local",
                    "pending_change": {"revision": e["event_id"], "action": e["operation"],
                                       "agent": e.get("agent", "unknown"), "device_id": e["device_id"],
                                       "base_revision": e.get("base_revision")}}
                if current is None:
                    fact.update({"created_at": None, "created_by_agent": e.get("agent", "unknown"),
                                 "created_by_device_id": e["device_id"], "updated_at": None,
                                 "updated_by_agent": e.get("agent", "unknown"),
                                 "updated_by_device_id": e["device_id"], "history": []})
                facts[e["fact_id"]] = fact
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
        if not url:
            raise ValueError("Server URL is not configured")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Invalid server URL")
        if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1") and not self.config.get("allow_private_http"):
            raise ValueError("Non-loopback HTTP requires explicit allow_private_http for your existing trusted transport")
        body = dumps(data).encode() if data is not None else None
        headers = {"Content-Type": "application/json"}
        if self.config.get("token"):
            headers["Authorization"] = "Bearer " + self.config["token"]
        req = urllib.request.Request(url + endpoint, data=body, method=method, headers=headers)
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
                "configured": bool(self.config.get("server_url"))}

    def conflicts(self):
        with connect(self.path) as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM conflicts")]

    @staticmethod
    def _parse_exported_note(markdown):
        """Parse the small frontmatter subset emitted by this exporter."""
        if not markdown.startswith("---\n"):
            raise ValueError("Missing frontmatter")
        header, separator, body = markdown[4:].partition("\n---\n")
        if not separator:
            raise ValueError("Unclosed frontmatter")
        props = {}
        for line in header.splitlines():
            key, colon, raw = line.partition(":")
            if not colon:
                continue
            raw = raw.strip()
            try:
                value = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                value = raw.strip("\"'")
            props[key.strip()] = value
        fact_id = props.get("fact_id")
        if not isinstance(fact_id, str):
            raise ValueError("Missing fact_id")
        identifier(fact_id)
        begin = f"<!-- memory-share:{fact_id}:content:start -->"
        end = f"<!-- memory-share:{fact_id}:content:end -->"
        if begin not in body or end not in body:
            raise ValueError("Editable content markers are missing")
        before, segment = body.split(begin, 1)
        content, found, _after = segment.partition(end)
        if not found:
            raise ValueError("Editable content end marker is missing")
        if content.startswith("\n"):
            content = content[1:]
        if content.endswith("\n"):
            content = content[:-1]
        title = next((line[2:].strip() for line in before.splitlines() if line.startswith("# ")), "")
        if not title:
            title = props.get("title", "")
        title = " ".join(str(title).split())
        if not title:
            raise ValueError("Missing title")
        return {"fact_id": fact_id, "revision": props.get("revision"),
                "pending": props.get("pending") is True,
                "pending_base_revision": props.get("pending_base_revision"),
                "scope": props.get("scope"), "certainty": props.get("certainty", "candidate"),
                "title": title, "content": content, "source": props.get("source", "")}

    @staticmethod
    def _note_body(fact):
        fact_id = fact["id"]
        title = " ".join(str(fact.get("title") or "Shared memory").split())
        body = (f"---\nfact_id: {json.dumps(fact_id)}\ntitle: {json.dumps(title)}\n"
                f"revision: {json.dumps(fact['revision'])}\n"
                f"pending_base_revision: {json.dumps((fact.get('pending_change') or {}).get('base_revision'))}\n"
                f"scope: {json.dumps(fact['scope'])}\nstatus: {fact['status']}\ncertainty: {fact['certainty']}\n"
                f"source: {json.dumps(fact.get('source', ''))}\n"
                f"pending: {str(bool(fact.get('pending'))).lower()}\n"
                f"created_at: {json.dumps(fact.get('created_at'))}\n"
                f"created_by_agent: {json.dumps(fact.get('created_by_agent', 'unknown'))}\n"
                f"created_by_device_id: {json.dumps(fact.get('created_by_device_id', 'unknown'))}\n"
                f"created_network_peer: {json.dumps(fact.get('created_network_peer'))}\n"
                f"updated_at: {json.dumps(fact.get('updated_at'))}\n"
                f"updated_by_agent: {json.dumps(fact.get('updated_by_agent', fact.get('agent', 'unknown')))}\n"
                f"updated_by_device_id: {json.dumps(fact.get('updated_by_device_id', fact.get('device_id', 'unknown')))}\n"
                f"updated_network_peer: {json.dumps(fact.get('updated_network_peer'))}\n---\n\n"
                "<!-- Edit the heading and text between the content markers; saved changes sync automatically. -->\n"
                f"\n# {title}\n\n<!-- memory-share:{fact_id}:content:start -->\n"
                f"{fact['content']}\n<!-- memory-share:{fact_id}:content:end -->\n")
        history = fact.get("history", [])
        if history:
            body += "\n## 修改记录\n\n| 时间（UTC） | 操作 | Agent | 设备 | 网络来源 | Revision |\n|---|---|---|---|---|---|\n"
            for item in history:
                recorded = item.get("recorded_at")
                when = (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(recorded)) + " UTC"
                        if isinstance(recorded, (int, float)) else "未知（旧版记忆）")
                cells = [when, str(item.get("action", "unknown")), str(item.get("agent", "unknown")),
                         str(item.get("device_id", "unknown")), str(item.get("network_peer", "")),
                         str(item.get("revision", "unknown"))]
                body += "| " + " | ".join(value.replace("|", "\\|").replace("\n", " ") for value in cells) + " |\n"
        if fact.get("pending_change"):
            change = fact["pending_change"]
            body += (f"\n> 待同步修改：{change.get('action', 'update')}，由 Agent `"
                     f"{change.get('agent', 'unknown')}`（设备 `{change.get('device_id', 'unknown')}`）提交。"
                     "同步确认后会进入正式修改记录。\n")
        return body

    def _save_edit_conflict(self, vault, markdown, parsed, current, reason):
        folder = Path(vault) / "41-Memory-Notes" / "Shared-Memory-Conflicts"
        folder.mkdir(parents=True, exist_ok=True)
        fact_id = (parsed or {}).get("fact_id") or (current or {}).get("id", "unknown")
        base = (parsed or {}).get("revision") or "unversioned"
        # Frontmatter is user-editable; never let a revision value escape this folder.
        base = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(base))[:80] or "unversioned"
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:10]
        path = folder / f"{fact_id}--{base}--{digest}.md"
        if not path.exists():
            latest = current or {}
            title = (parsed or {}).get("title") or latest.get("title", "Shared memory")
            content = (parsed or {}).get("content")
            if content is None:
                content = markdown
            body = (f"# 共享记忆编辑待合并：{title}\n\n原因：{reason}\n\n"
                    f"基础 revision：`{base}`\n当前 revision：`{latest.get('revision', 'unknown')}`\n\n"
                    "## Obsidian 中保留的修改\n\n" + content + "\n\n"
                    "## 当前共享版本\n\n" + latest.get("content", "（当前版本不可用）") + "\n")
            atomic_write(path, body, private=False)
        return path

    def _publish_conflict_notes(self, vault):
        folder = Path(vault) / "41-Memory-Notes" / "Shared-Memory-Conflicts"
        conflicts = self.conflicts()
        for conflict in conflicts:
            event = conflict.get("event", {})
            fact_id = event.get("fact_id", "unknown")
            event_id = conflict.get("id", "unknown")
            path = folder / f"{fact_id}--conflict--{event_id}.md"
            if path.exists():
                continue
            folder.mkdir(parents=True, exist_ok=True)
            current = conflict.get("current_at_conflict") or {}
            body = (f"# 共享记忆冲突：{event.get('title', 'Shared memory')}\n\n"
                    f"冲突事件：`{event_id}`；基础 revision：`{event.get('base_revision')}`\n\n"
                    f"## 当前共享版本（{current.get('revision', 'unknown')}）\n\n{current.get('content', '')}\n\n"
                    f"## 未应用的修改（Agent {event.get('agent', 'unknown')}）\n\n{event.get('content', '')}\n\n"
                    "请比较两版后，通过 Agent 调用 `memory_resolve` 提交合并结果。")
            atomic_write(path, body, private=False)
        return len(conflicts)

    def export(self):
        vault = self.config.get("vault")
        if not vault:
            raise ValueError("Vault not configured")
        vault = Path(vault).resolve()
        target = vault / "40-Agent-Memory" / "Generated"
        target.mkdir(parents=True, exist_ok=True)
        with process_lock(self.root / "export.lock"):
            manifest_file = self.root / "export-manifest.json"
            manifest = json.loads(manifest_file.read_text(encoding="utf-8")) if manifest_file.exists() else {}
            with connect(self.path) as db:
                db.execute("BEGIN")
                facts = self._view(db)
            new = dict(manifest)
            preserved = []
            written = 0
            imported = 0
            conflicts_saved = 0
            for fact_id, f in facts.items():
                identifier(fact_id)
                candidates = [name for name in manifest if _export_fact_id(name) == fact_id]
                original_name = next((name for name in candidates if (target / name).exists()), None)
                if original_name is None:
                    original_name = _export_filename(f.get("title"), fact_id)
                original_path = target / original_name
                existing = original_path.read_text(encoding="utf-8") if original_path.exists() else None
                existing_hash = hashlib.sha256(existing.encode("utf-8")).hexdigest() if existing is not None else None
                baseline_hash = manifest.get(original_name)

                if existing is not None and existing_hash != baseline_hash:
                    try:
                        edit = self._parse_exported_note(existing)
                        if edit["fact_id"] != fact_id or edit["scope"] != f["scope"]:
                            raise ValueError("Fact ID or scope was changed")
                        if edit["certainty"] not in ("candidate", "confirmed"):
                            raise ValueError("certainty must be candidate or confirmed")
                    except (ValueError, TypeError) as exc:
                        draft = self._save_edit_conflict(vault, existing, None, f, f"无法安全解析 Obsidian 修改：{exc}")
                        preserved.append(str(draft.relative_to(vault)))
                        conflicts_saved += 1
                    else:
                        same_as_current = all(edit[k] == f.get(k) for k in ("title", "content", "certainty"))
                        if not same_as_current:
                            base_revision = (f["revision"] if f.get("pending_change") else
                                             (edit.get("pending_base_revision") if edit.get("pending") else None)
                                             or edit.get("revision"))
                            if base_revision != f["revision"]:
                                draft = self._save_edit_conflict(vault, existing, edit, f,
                                    "此笔记基于较旧 revision；原修改已保存为待合并草稿。")
                                preserved.append(str(draft.relative_to(vault)))
                                conflicts_saved += 1
                            else:
                                self.enqueue("update", fact_id=fact_id, base_revision=base_revision,
                                    title=edit["title"], content=edit["content"], scope=edit["scope"],
                                    source=edit.get("source") or f.get("source", ""),
                                    certainty=edit["certainty"], agent="obsidian")
                                f = self.get(fact_id) or f
                                facts[fact_id] = f
                                imported += 1

                filename = _export_filename(f.get("title"), fact_id)
                path = target / filename
                body = self._note_body(f)
                if existing != body or original_path != path:
                    atomic_write(path, body, private=False)
                    written += 1
                if original_path != path and original_path.exists():
                    # The edit has either been queued or copied into a visible conflict draft.
                    original_path.unlink()
                    new.pop(original_name, None)
                new[path.name] = hashlib.sha256(body.encode()).hexdigest()
            # Stale pages are removed only when still byte-identical to our own export.
            for name in list(manifest):
                if _export_fact_id(name) not in facts:
                    path = target / name
                    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == manifest[name]:
                        path.unlink()
                        new.pop(name, None)
                    elif path.exists():
                        preserved.append(name)
            atomic_write(manifest_file, dumps(new))
        conflicts_published = self._publish_conflict_notes(vault)
        return {"written": written, "imported_edits": imported, "conflicts_saved": conflicts_saved,
                "conflicts_published": conflicts_published, "preserved_user_edits": preserved,
                "directory": str(target)}

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
