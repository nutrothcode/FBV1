from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from backend.run import run_server
from fbv1_app import FacebookToolApp


def _backend_health_url() -> str:
    base_url = os.environ.get("FBV1_BACKEND_URL", "http://127.0.0.1:8010").rstrip("/")
    return f"{base_url}/api/health"


def _backend_socket_target() -> tuple[str, int]:
    base_url = os.environ.get("FBV1_BACKEND_URL", "http://127.0.0.1:8010").rstrip("/")
    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8010
    return host, port


def _backend_port_in_use() -> bool:
    host, port = _backend_socket_target()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _backend_is_ready() -> bool:
    request = urllib.request.Request(_backend_health_url(), headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
        return str(payload.get("status")) == "ok"
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return False


def _ensure_embedded_backend() -> None:
    if _backend_is_ready():
        return

    if _backend_port_in_use():
        return

    thread = threading.Thread(target=lambda: run_server(reload=False), daemon=True)
    thread.start()

    for _ in range(30):
        if _backend_is_ready():
            return
        time.sleep(0.2)


def main() -> None:
    _ensure_embedded_backend()
    app = FacebookToolApp()
    app.run()


if __name__ == "__main__":
    main()
