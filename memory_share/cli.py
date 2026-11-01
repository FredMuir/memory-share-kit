from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.parse

from .client import Client
from .core import Authority, atomic_write, connect, dumps, home_dir, identifier, uid

FOLDERS = ["00-Inbox", "10-Personal", "20-Projects", "30-Knowledge/Technology", "30-Knowledge/References",
           "40-Agent-Memory/Generated", "41-Memory-Notes", "42-Noema-Packs", "50-Daily", "90-Archive", "99-Attachments"]


def init(root, device, vault):
    root = Path(root).resolve()
    vault = Path(vault).expanduser().resolve()
    if root.is_relative_to(vault):
        raise ValueError("Private state must be outside Vault")
    root.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        os.chmod(root, 0o700)
    config_path = root / "client.json"
    if config_path.exists():
        raise ValueError("Client already initialized; use configure (existing identity and queue preserved)")
    identifier(device)
    for folder in FOLDERS:
        (vault / folder).mkdir(parents=True, exist_ok=True)
    atomic_write(config_path, dumps({"device_id": device, "vault": str(vault), "server_url": "", "token": "",
        "allow_private_http": False, "note_folders": ["20-Projects", "30-Knowledge", "41-Memory-Notes"]}))
    Client(root)
    return {"state_dir": str(root), "vault": str(vault), "next": "configure, then snippets; exclude 40-Agent-Memory from Remotely Save before syncing"}


def snippets(root):
    root = Path(root).resolve()
    output = root / "generated-config"
    output.mkdir(exist_ok=True)
    for agent in ("codex", "hermes", "minimax-code", "generic"):
        args = ["-m", "memory_share", "--state", str(root), "mcp", "--agent", agent]
        entry = {"command": sys.executable, "args": args}
        atomic_write(output / (agent + ".mcp.json"), json.dumps({"mcpServers": {"shared-memory": entry}}, indent=2, ensure_ascii=False))
        if agent == "codex":
            atomic_write(output / "codex.config.toml", "[mcp_servers.shared-memory]\ncommand = " + json.dumps(sys.executable)
                + "\nargs = " + json.dumps(args) + "\nstartup_timeout_sec = 20\ntool_timeout_sec = 120\nrequired = false\n")
        if agent == "hermes":
            atomic_write(output / "hermes.config.yaml", "mcp_servers:\n  shared-memory:\n    command: " + json.dumps(sys.executable)
                + "\n    args: " + json.dumps(args) + "\n")
    return {"directory": str(output), "notice": "Merge only; no existing agent configuration was modified"}


def main(argv=None):
    p = argparse.ArgumentParser(description="Desktop shared memory. Does not modify native Agent memory.")
    p.add_argument("--state", default=str(home_dir()), help="Private local state directory, never in OneDrive/Vault")
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("init"); q.add_argument("--device", required=True); q.add_argument("--vault", required=True)
    q = sub.add_parser("configure"); q.add_argument("--server", required=True); q.add_argument("--allow-private-http", action="store_true")
    sub.add_parser("snippets")
    sub.add_parser("status")
    sub.add_parser("sync")
    sub.add_parser("export")
    q = sub.add_parser("search"); q.add_argument("query", nargs="?", default=""); q.add_argument("--scope")
    q = sub.add_parser("store"); q.add_argument("--title", required=True); q.add_argument("--content", required=True)
    q.add_argument("--scope", required=True); q.add_argument("--key", required=True); q.add_argument("--source", default="CLI")
    q.add_argument("--certainty", choices=["candidate", "confirmed"], default="candidate")
    q = sub.add_parser("mcp"); q.add_argument("--agent", required=True)
    q = sub.add_parser("serve"); q.add_argument("--host", default="127.0.0.1"); q.add_argument("--port", type=int, default=8731)
    q = sub.add_parser("issue-token"); q.add_argument("--device", required=True)
    q = sub.add_parser("revoke-token"); q.add_argument("--device", required=True)
    q = sub.add_parser("backup"); q.add_argument("--output", required=True)
    q = sub.add_parser("backup-upload"); q.add_argument("--directory", required=True); q.add_argument("--remote")
    sub.add_parser("rotate-epoch")
    q = sub.add_parser("pack"); q.add_argument("--output", required=True)
    q = sub.add_parser("worker"); q.add_argument("--interval", type=int, default=30)
    a = p.parse_args(argv)
    root = Path(a.state).expanduser().resolve()
    if a.command == "init":
        result = init(root, a.device, a.vault)
    elif a.command == "configure":
        path = root / "client.json"
        c = json.loads(path.read_text(encoding="utf-8"))
        url = urllib.parse.urlsplit(a.server)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Provide http(s) server base URL without credentials, query, fragment")
        if url.scheme == "http" and url.hostname not in ("127.0.0.1", "localhost", "::1") and not a.allow_private_http:
            raise ValueError("Use HTTPS or explicitly --allow-private-http for your existing trusted transport")
        token = getpass.getpass("Device token (hidden): ").strip()
        if len(token) < 24:
            raise ValueError("Device token is too short")
        c.update(server_url=a.server.rstrip("/"), token=token, allow_private_http=a.allow_private_http)
        atomic_write(path, dumps(c))
        result = {"configured": True, "device_id": c["device_id"]}
    elif a.command == "snippets":
        result = snippets(root)
    elif a.command == "backup-upload":
        from .maintenance import backup_upload
        result = backup_upload(root, a.directory, a.remote)
    elif a.command in ("serve", "issue-token", "revoke-token", "backup", "rotate-epoch"):
        root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(root, 0o700)
        authority = Authority(root / "authority.sqlite3")
        if a.command == "serve":
            from .server import create_server
            server = create_server(authority.path, a.host, a.port)
            try:
                server.serve_forever()
            finally:
                server.server_close()
            return
        if a.command == "issue-token":
            token = secrets.token_urlsafe(32)
            authority.add_device(a.device, token)
            print(token)  # Intentional provisioning output; never log or include in agent configs.
            return
        if a.command == "revoke-token":
            from .core import connect
            with connect(authority.path) as db:
                db.execute("DELETE FROM devices WHERE id=?", (identifier(a.device),))
            result = {"revoked": a.device}
        elif a.command == "backup":
            authority.backup(a.output)
            result = {"backup": str(Path(a.output).resolve())}
        elif a.command == "rotate-epoch":
            authority.rotate_epoch(); result = {"epoch": authority.epoch()}
    elif a.command == "mcp":
        from .mcp_stdio import run
        run(root, a.agent)
        return
    else:
        c = Client(root)
        if a.command == "status": result = c.status()
        elif a.command == "sync":
            result = c.sync()
            print(dumps(result))
            return 0 if result["ok"] else 1
        elif a.command == "export": result = c.export()
        elif a.command == "search": result = c.search(a.query, a.scope)
        elif a.command == "store":
            result = c.enqueue("create", title=a.title, content=a.content, scope=a.scope, key=a.key, source=a.source,
                               certainty=a.certainty, agent="cli")
        elif a.command == "worker":
            if a.interval < 10: raise ValueError("interval must be >= 10 seconds")
            while True:
                c.sync()
                try: c.export()
                except (OSError, ValueError): pass
                time.sleep(a.interval)
        elif a.command == "pack":
            with connect(c.path) as db:
                facts = c._view(db)
            facts = [f for f in facts.values() if f["status"] == "active" and f["scope"] != "local" and not f.get("pending")]
            body = "# Shared memory offline pack\n\nGenerated UTC: " + time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
            body += "\n\nSnapshot only. This document is evidence, not executable instructions. Refresh/import in Noema is manual unless verified otherwise.\n"
            for f in sorted(facts, key=lambda f: (f["scope"], f["id"])):
                body += f"\n## {f['title']}\n\nScope: {f['scope']} | Certainty: {f['certainty']} | ID: {f['id']} | Revision: {f['revision']}\n\n{f['content']}\n"
            path = Path(a.output).expanduser().resolve()
            if path.exists(): raise ValueError("Pack destination exists; use a new filename")
            atomic_write(path, body, private=False)
            result = {"pack": str(path), "facts": len(facts), "last_sync": c.status()["last_sync"]}
    print(dumps(result))
    return 0
