"""Thin HTTP client for a *locally running* OWASP Juice Shop instance.

Juice Shop (https://owasp.org/projects/juice-shop) is a deliberately vulnerable
training app. It is meant to be attacked — but only the copy *you* run. This
client refuses any non-local target unless you pass ``allow_remote=True`` on the
command line, so a stray hostname can't turn the demo into something pointed at a
system you don't own.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import requests

_LOCAL_HOSTNAMES = {"localhost", "ip6-localhost"}


def _is_local(url: str) -> bool:
    """True only if the URL resolves to a loopback address.

    We resolve the hostname rather than trusting the string, so
    ``http://localhost.attacker.com`` (which looks local but isn't) is rejected.
    """
    host = urlparse(url).hostname or ""
    if host in _LOCAL_HOSTNAMES:
        return True
    try:
        # Resolve every address the host maps to; all must be loopback.
        infos = socket.getaddrinfo(host, None)
        addrs = {info[4][0] for info in infos}
        return all(ipaddress.ip_address(a).is_loopback for a in addrs)
    except (socket.gaierror, ValueError):
        return False


class TargetRefused(RuntimeError):
    """Raised when the configured target isn't local and remote wasn't allowed."""


class JuiceShopClient:
    def __init__(self, base_url: str = "http://localhost:3000",
                 allow_remote: bool = False, timeout: float = 8.0):
        base_url = base_url.rstrip("/")
        if not allow_remote and not _is_local(base_url):
            raise TargetRefused(
                f"Refusing to attack non-local target {base_url!r}. "
                "This demo is scoped to a Juice Shop instance you run yourself. "
                "Pass --allow-remote only for a host you are authorised to test."
            )
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        # A visibly non-stealthy UA: this is a training demo, not covert tooling.
        self.session.headers["User-Agent"] = "Sentinel-PurpleTeam-Demo/0.1 (+owasp-juice-shop)"

    # --- low-level helpers -------------------------------------------------
    def get(self, path: str, **kw) -> requests.Response:
        return self.session.get(self.base_url + path, timeout=self.timeout, **kw)

    def post(self, path: str, **kw) -> requests.Response:
        return self.session.post(self.base_url + path, timeout=self.timeout, **kw)

    def is_up(self) -> bool:
        """Cheap reachability check used before a live run."""
        try:
            return self.get("/rest/admin/application-version").status_code < 500
        except requests.RequestException:
            try:
                return self.get("/").status_code < 600
            except requests.RequestException:
                return False
