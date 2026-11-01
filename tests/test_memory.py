import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from memory_share.client import Client
from memory_share.cli import init, snippets
from memory_share.core import Authority, atomic_write, connect, dumps, uid
from memory_share.server import create_server


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.auth = Authority(self.root / "server.sqlite3")
        self.server = create_server(self.auth.path, port=0)
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.a = self.make_client("a")
        self.b = self.make_client("b")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def make_client(self, name):
        state = self.root / name
        init(state, name, self.root / (name + "-vault"))
        config = json.loads((state / "client.json").read_text())
        token = "test-token-" + name + "x" * 30
        config.update(server_url=self.url, token=token)
        atomic_write(state / "client.json", dumps(config))
        self.auth.add_device(name, token)
        return Client(state)

    def store(self, c, key="decision", content="已验证内容", scope="project:demo"):
        return c.enqueue("create", title="测试事实", content=content, scope=scope, key=key, certainty="confirmed", agent="test")

    def event(self, c, event_id):
        with connect(c.path) as db:
            return json.loads(db.execute("SELECT event FROM outbox WHERE id=?", (event_id,)).fetchone()[0])

    def test_offline_save_survives_real_process_exit(self):
        result = subprocess.run([sys.executable, "-m", "memory_share", "--state", str(self.a.root), "store", "--title", "离线", "--content", "断网新增", "--scope", "global", "--key", "offline"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        restarted = Client(self.a.root)
        self.assertEqual(restarted.search("断网")[0]["content"], "断网新增")
        self.assertTrue(restarted.sync()["ok"])
        self.assertTrue(self.b.sync()["ok"])
        self.assertEqual(len(self.b.search("断网")), 1)

    def test_offline_http_failure_then_real_reconnect(self):
        self.store(self.a)
        self.a.config["server_url"] = "http://127.0.0.1:1"
        self.assertFalse(self.a.sync()["ok"])
        self.assertEqual(self.a.status()["counts"]["pending"], 1)
        self.assertEqual(len(self.a.search("已验证")), 1)
        self.a.config["server_url"] = self.url
        self.assertTrue(self.a.sync()["ok"])

    def test_response_lost_after_server_commit(self):
        r = self.store(self.a)
        self.auth.apply(self.event(self.a, r["event_id"]), "a")
        # Client has no receipt, exactly as after a lost HTTP response.
        for _ in range(3): self.assertTrue(self.a.sync()["ok"])
        self.assertEqual(len(self.auth.snapshot()["facts"]), 1)
        with connect(self.auth.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_actual_socket_disconnect_after_commit(self):
        r = self.store(self.a)
        handler = self.server.RequestHandlerClass
        original = handler.send_json
        dropped = []
        def send(instance, status, obj):
            if instance.path == "/v1/events" and status == 200 and not dropped:
                dropped.append(True)
                instance.connection.shutdown(socket.SHUT_RDWR)
                instance.connection.close()
                return
            return original(instance, status, obj)
        handler.send_json = send
        try:
            self.assertFalse(self.a.sync()["ok"])
        finally:
            handler.send_json = original
        self.assertEqual(self.a.status()["counts"]["pending"], 1)
        self.assertEqual(self.auth.snapshot()["facts"][0]["id"], r["fact_id"])
        self.assertTrue(self.a.sync()["ok"])
        self.assertEqual(self.auth.snapshot()["cursor"], 1)

    def test_same_event_replayed_100_times(self):
        r = self.store(self.a)
        e = self.event(self.a, r["event_id"])
        expected = self.auth.apply(e, "a")
        for _ in range(100): self.assertEqual(self.auth.apply(e, "a"), expected)
        self.assertEqual(self.auth.snapshot()["cursor"], 1)

    def test_same_key_same_value_from_two_devices(self):
        self.store(self.a); self.store(self.b)
        self.assertTrue(self.a.sync()["ok"]); self.assertTrue(self.b.sync()["ok"])
        self.assertEqual(len(self.auth.snapshot()["facts"]), 1)
        self.assertEqual(len(self.auth.snapshot()["conflicts"]), 0)
        self.assertEqual(self.b.status()["counts"]["noop"], 1)

    def test_concurrent_update_and_explicit_resolution(self):
        r = self.store(self.a)
        self.a.sync(); self.b.sync()
        f = self.a.get(r["fact_id"])
        for c, value in [(self.a, "A修改"), (self.b, "B修改")]:
            c.enqueue("update", fact_id=f["id"], base_revision=f["revision"], title=f["title"], content=value,
                      scope=f["scope"], certainty="confirmed")
        with ThreadPoolExecutor(2) as pool:
            self.assertTrue(all(x["ok"] for x in pool.map(lambda c: c.sync(), (self.a, self.b))))
        self.a.sync(); self.b.sync()
        conflicts = self.a.conflicts()
        self.assertEqual(len(conflicts), 1)
        current = self.a.get(f["id"])
        self.a.enqueue("resolve", resolves_event_id=conflicts[0]["id"], fact_id=f["id"], base_revision=current["revision"],
                       scope=current["scope"], title=current["title"], content="用户选择的合并", certainty="confirmed")
        self.a.sync(); self.b.sync()
        self.assertEqual(self.b.get(f["id"])["content"], "用户选择的合并")
        self.assertEqual(self.b.conflicts(), [])

    def test_retraction_not_resurrected_by_stale_edit(self):
        r = self.store(self.a); self.a.sync(); self.b.sync()
        f = self.a.get(r["fact_id"])
        self.a.enqueue("retract", fact_id=f["id"], base_revision=f["revision"], title=f["title"], content=f["content"], scope=f["scope"], certainty="confirmed")
        self.b.enqueue("update", fact_id=f["id"], base_revision=f["revision"], title=f["title"], content="旧设备", scope=f["scope"], certainty="confirmed")
        self.a.sync(); self.b.sync()
        self.assertEqual(self.b.get(f["id"])["status"], "retracted")
        self.assertEqual(self.b.search("旧设备"), [])
        self.assertEqual(len(self.auth.snapshot()["conflicts"]), 1)

    def test_chained_offline_edits(self):
        r = self.store(self.a)
        self.a.enqueue("update", fact_id=r["fact_id"], base_revision=r["revision"], title="第二版", content="第二版内容", scope="project:demo", certainty="confirmed")
        self.assertTrue(self.a.sync()["ok"]); self.b.sync()
        self.assertEqual(self.b.get(r["fact_id"])["content"], "第二版内容")

    def test_local_scope_never_uploaded(self):
        self.store(self.a, scope="local"); self.a.sync(); self.b.sync()
        self.assertEqual(len(self.a.search("已验证")), 1)
        self.assertEqual(self.b.search("已验证"), [])
        self.assertEqual(self.auth.snapshot()["facts"], [])

    def test_local_scope_concurrent_stale_edit_is_explicit_error(self):
        r = self.store(self.a, scope="local")
        kwargs = {"fact_id": r["fact_id"], "base_revision": r["revision"], "title": "本机事实", "content": "新值", "scope": "local"}
        self.a.enqueue("update", **kwargs)
        with self.assertRaisesRegex(ValueError, "Local revision changed"):
            self.a.enqueue("update", **kwargs)

    def test_backup_restore_epoch_replays_acknowledged_writes(self):
        self.a.sync()
        backup = self.root / "backup.sqlite3"
        self.auth.backup(backup)
        r = self.store(self.a); self.a.sync()
        # Actual SQLite restore via backup API, no fake server.
        with sqlite3.connect(backup) as src, sqlite3.connect(self.auth.path) as dst:
            src.backup(dst)
        self.auth.rotate_epoch()
        self.assertEqual(self.auth.snapshot()["facts"], [])
        self.assertTrue(self.a.sync()["ok"])
        self.assertEqual(self.auth.snapshot()["facts"][0]["id"], r["fact_id"])

    def test_auth_device_spoof_and_id_reuse(self):
        r = self.store(self.a); e = self.event(self.a, r["event_id"])
        with self.assertRaises(ValueError): self.auth.apply(e, "b")
        self.auth.apply(e, "a"); e["content"] = "tamper"
        with self.assertRaises(ValueError): self.auth.apply(e, "a")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url + "/v1/snapshot")
        self.assertEqual(caught.exception.code, 401)

    def test_export_preserves_user_edits_and_no_rewrite(self):
        r = self.store(self.a); self.a.sync()
        result = self.a.export(); self.assertEqual(result["written"], 1)
        p = Path(result["directory"]) / (r["fact_id"] + ".md")
        self.assertTrue(p.read_text().startswith("---\n"))
        stamp = p.stat().st_mtime_ns
        self.assertEqual(self.a.export()["written"], 0)
        self.assertEqual(stamp, p.stat().st_mtime_ns)
        p.write_text("我的直接编辑", encoding="utf-8")
        self.assertIn(p.name, self.a.export()["preserved_user_edits"])
        self.assertEqual(p.read_text(), "我的直接编辑")

    def test_note_allowlist_blocks_traversal_and_symlink(self):
        vault = Path(self.a.config["vault"])
        p = vault / "20-Projects/test.md"; p.write_text("项目内容", encoding="utf-8")
        self.assertEqual(self.a.note_read("20-Projects/test.md")["content"], "项目内容")
        with self.assertRaises(ValueError): self.a.note_read("../../server.sqlite3")
        outside = self.root / "secret.md"; outside.write_text("secret")
        try: (vault / "20-Projects/link.md").symlink_to(outside)
        except OSError: return
        with self.assertRaises(ValueError): self.a.note_read("20-Projects/link.md")

    def test_init_does_not_replace_identity_or_queue(self):
        self.store(self.a)
        with self.assertRaises(ValueError): init(self.a.root, "another", self.a.config["vault"])
        self.assertEqual(Client(self.a.root).status()["counts"]["pending"], 1)

    def test_config_snippets_parse_and_have_no_token(self):
        import tomllib
        output = Path(snippets(self.a.root)["directory"])
        t = tomllib.loads((output / "codex.config.toml").read_text())
        self.assertEqual(t["mcp_servers"]["shared-memory"]["command"], sys.executable)
        for p in output.glob("*"):
            self.assertNotIn(self.a.config["token"], p.read_text())

    def test_real_mcp_stdio_offline_read_and_write(self):
        config = json.loads((self.a.root / "client.json").read_text())
        config["server_url"] = "http://127.0.0.1:1"
        atomic_write(self.a.root / "client.json", dumps(config))
        async def exercise():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(command=sys.executable, args=["-m", "memory_share", "--state", str(self.a.root), "mcp", "--agent", "test-mcp"])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self.assertIn("memory_store", [t.name for t in listed.tools])
                    result = await session.call_tool("memory_store", {"title": "MCP真实写入", "content": "实际SDK传输", "scope": "global", "key": "mcp-real"})
                    self.assertFalse(result.isError)
                    result = await session.call_tool("memory_search", {"query": "实际SDK"})
                    self.assertFalse(result.isError)
                    self.assertIn("实际SDK传输", str(result))
        asyncio.run(exercise())

    def test_receipt_keeps_local_write_readable_if_pull_fails(self):
        r = self.store(self.a)
        self.a.sync()
        with connect(self.a.path) as db:
            db.execute("DELETE FROM facts")  # Represents a receipt committed before the subsequent pull.
        self.assertEqual(Client(self.a.root).get(r["fact_id"])["content"], "已验证内容")

    def test_old_receipt_cannot_override_newer_retraction(self):
        r = self.store(self.a); self.a.sync(); self.b.sync()
        f = self.b.get(r["fact_id"])
        self.b.enqueue("retract", fact_id=f["id"], base_revision=f["revision"], title=f["title"], content=f["content"], scope=f["scope"], certainty="confirmed")
        self.b.sync(); self.a.sync()
        self.assertEqual(self.a.get(f["id"])["status"], "retracted")

    def test_interrupted_pull_rolls_back_cursor_and_facts_together(self):
        self.b.sync()
        self.store(self.a, key="one"); self.store(self.a, key="two"); self.a.sync()
        original = self.b._change
        calls = []
        def interrupt(db, change):
            original(db, change)
            calls.append(1)
            raise ValueError("simulated process interruption inside local transaction")
        self.b._change = interrupt
        self.assertFalse(self.b.sync()["ok"])
        with connect(self.b.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='cursor'").fetchone()[0], "0")
        self.b._change = original
        self.assertTrue(self.b.sync()["ok"])
        self.assertEqual(len(self.b.search("已验证")), 2)

    def test_local_backup_upload_reports_no_remote_verification(self):
        from memory_share.maintenance import backup_upload
        self.store(self.a); self.a.sync()
        # Use actual backup database, with no rclone remote configured.
        self.auth.backup(self.root / "authority.sqlite3")
        result = backup_upload(self.root, self.root / "backups")
        self.assertFalse(result["uploaded"])
        self.assertFalse(result["verified"])
        self.assertEqual(len(Authority(result["backup"]).snapshot()["facts"]), 1)


if __name__ == "__main__":
    unittest.main()
