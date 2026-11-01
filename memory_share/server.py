from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import urllib.parse

from .core import Authority, dumps


def create_server(db_path, host="127.0.0.1", port=8731, allow_unauthenticated_private_network=False):
    authority = Authority(db_path)

    class Handler(BaseHTTPRequestHandler):
        server_version = "MemoryShare/0.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *args):
            pass  # Do not log credentials, queries or memory text.

        def send_json(self, status, obj):
            body = dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def auth(self):
            auth = self.headers.get("Authorization", "")
            device = authority.authenticate(auth[7:]) if auth.startswith("Bearer ") else None
            if not device and allow_unauthenticated_private_network and self.private_peer():
                return "anonymous"
            if not device:
                self.send_json(401, {"error": "authentication required"})
            return device

        def private_peer(self):
            try:
                address = ipaddress.ip_address(self.client_address[0].split("%", 1)[0])
                if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                    address = address.ipv4_mapped
                shared_space = ipaddress.ip_network("100.64.0.0/10")
                return address.is_private or address in shared_space
            except ValueError:
                return False

        def allowed_source(self):
            if not allow_unauthenticated_private_network or self.private_peer():
                return True
            self.send_json(403, {"error": "service is limited to private LAN and overlay network peers"})
            return False

        def do_GET(self):
            if not self.allowed_source():
                return
            p = urllib.parse.urlsplit(self.path)
            if p.path == "/healthz":
                self.send_json(200, {"ok": True})
                return
            if not self.auth():
                return
            try:
                if p.path == "/v1/epoch":
                    result = {"epoch": authority.epoch()}
                elif p.path == "/v1/snapshot":
                    result = authority.snapshot()
                elif p.path == "/v1/changes":
                    q = urllib.parse.parse_qs(p.query)
                    after = int(q.get("after", ["0"])[0])
                    if after < 0:
                        raise ValueError("invalid cursor")
                    result = authority.changes(q.get("epoch", [""])[0], after)
                else:
                    self.send_json(404, {"error": "not found"})
                    return
                self.send_json(200, result)
            except (ValueError, KeyError):
                self.send_json(400, {"error": "invalid request"})

        def do_POST(self):
            if not self.allowed_source():
                return
            if self.path != "/v1/events":
                self.send_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 1 <= length <= 256 * 1024 or self.headers.get("Transfer-Encoding"):
                    self.send_json(413, {"error": "body must be 1..262144 bytes"})
                    return
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("object required")
                event = data.get("event")
                if not isinstance(event, dict):
                    raise ValueError("event object required")
                device = self.auth()
                if not device:
                    return
                if device == "anonymous":
                    # Device and agent labels are client-reported when no token is used;
                    # record the server-observed peer address to make that explicit.
                    event["network_peer"] = self.client_address[0]
                    event["agent_origin"] = "client-reported"
                    device = event.get("device_id")
                if data.get("epoch") != authority.epoch():
                    self.send_json(200, {"reset_required": True})
                    return
                self.send_json(200, authority.apply(event, device))
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                self.send_json(400, {"error": "event validation failed"})

    class Server(ThreadingHTTPServer):
        daemon_threads = True

    return Server((host, port), Handler)
