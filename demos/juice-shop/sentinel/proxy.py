"""Optional live mitigating reverse proxy — the "fix it in the browser" moment.

Run Juice Shop on :3000 (vulnerable) and this proxy on :8080 (defended). Browsing
through :8080, Blue's compensating controls are enforced on real traffic:

    [ browser ] --> :8080 Sentinel proxy --> :3000 Juice Shop
                         |
                         +-- blocks SQLi requests (403)
                         +-- guards /ftp
                         +-- injects security headers
                         +-- redacts the version endpoint

This is a demo aid, not a production WAF. It deliberately uses only the stdlib
http.server plus requests so there's nothing extra to install.

    python -m sentinel.proxy --upstream http://localhost:3000 --port 8080
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from .blue_agent import _FTP_PATH, _SQLI_SIGNATURE

_SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
_BLOCK_BODY = json.dumps({
    "error": "Request blocked by Sentinel compensating control",
    "control": None,
}).encode()
_HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "content-encoding",
               "content-length", "te", "trailer", "upgrade", "proxy-authorization"}


def _make_handler(upstream: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quieter console during a demo
            pass

        # one implementation serves both verbs
        def do_GET(self):  # noqa: N802
            self._proxy("GET")

        def do_POST(self):  # noqa: N802
            self._proxy("POST")

        def _blocked(self, control: str):
            body = json.dumps({
                "error": "Request blocked by Sentinel compensating control",
                "control": control,
            }).encode()
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Sentinel-Control", control)
            for k, v in _SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _proxy(self, method: str):
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            haystack = self.path + " " + raw.decode("utf-8", "replace")

            # --- request blockers (run before forwarding) ---
            if _FTP_PATH.search(self.path.split("?")[0]):
                return self._blocked("ftp-path-guard")
            if _SQLI_SIGNATURE.search(haystack):
                return self._blocked("sql-injection-filter")

            # --- forward to upstream ---
            fwd_headers = {k: v for k, v in self.headers.items()
                           if k.lower() not in _HOP_BY_HOP and k.lower() != "host"}
            try:
                r = requests.request(method, upstream + self.path, data=raw or None,
                                     headers=fwd_headers, timeout=15, allow_redirects=False)
            except requests.RequestException as e:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(f"upstream error: {e}".encode())
                return

            # --- response transforms (run after) ---
            content = r.content
            if self.path.split("?")[0] == "/rest/admin/application-version":
                content = json.dumps({"version": "redacted"}).encode()  # version-redactor

            self.send_response(r.status_code)
            for k, v in r.headers.items():
                if k.lower() not in _HOP_BY_HOP:
                    self.send_header(k, v)
            for k, v in _SECURITY_HEADERS.items():  # security-headers-injector
                self.send_header(k, v)
            self.send_header("X-Sentinel-Defended", "true")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Sentinel live mitigating proxy")
    ap.add_argument("--upstream", default="http://localhost:3000",
                    help="the vulnerable Juice Shop instance")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), _make_handler(args.upstream.rstrip("/")))
    print(f"Sentinel proxy defending {args.upstream}  ->  http://localhost:{args.port}")
    print("Browse the defended app on the proxy port. Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()
