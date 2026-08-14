"""Keep Cloud Run's ingress port open while vLLM loads a large model."""

from __future__ import annotations

import http.client
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PROXY_PORT = int(os.environ.get("PORT", "8080"))
VLLM_PORT = 8000
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def vllm_arguments(arguments: list[str]) -> list[str]:
    """Force vLLM onto the private loopback port controlled by this proxy."""
    result: list[str] = []
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
            continue
        if argument in {"--host", "--port"}:
            skip_next = True
            continue
        if argument.startswith("--host=") or argument.startswith("--port="):
            continue
        result.append(argument)
    return [*result, "--host=127.0.0.1", f"--port={VLLM_PORT}"]


BACKEND = subprocess.Popen(
    [
        "python3",
        "-m",
        "vllm.entrypoints.openai.api_server",
        *vllm_arguments(sys.argv[1:]),
    ]
)


class StartupProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self.forward()

    def do_POST(self) -> None:  # noqa: N802
        self.forward()

    def do_PUT(self) -> None:  # noqa: N802
        self.forward()

    def do_DELETE(self) -> None:  # noqa: N802
        self.forward()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.forward()

    def forward(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(content_length) if content_length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
        }

        try:
            connection = http.client.HTTPConnection("127.0.0.1", VLLM_PORT, timeout=1400)
            connection.request(self.command, self.path, body=request_body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() not in HOP_BY_HOP_HEADERS:
                    self.send_header(key, value)
            self.end_headers()
            while chunk := response.read(64 * 1024):
                self.wfile.write(chunk)
            connection.close()
        except (ConnectionError, OSError, http.client.HTTPException):
            payload = b'{"error":{"message":"Model is warming up","type":"service_unavailable"}}'
            self.send_response(503, "Service Unavailable")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Retry-After", "15")
            self.end_headers()
            self.wfile.write(payload)


def stop_backend(*_: object) -> None:
    if BACKEND.poll() is None:
        BACKEND.terminate()


def watch_backend(server: ThreadingHTTPServer) -> None:
    BACKEND.wait()
    server.shutdown()


server = ThreadingHTTPServer(("0.0.0.0", PROXY_PORT), StartupProxy)
signal.signal(signal.SIGTERM, stop_backend)
signal.signal(signal.SIGINT, stop_backend)
threading.Thread(target=watch_backend, args=(server,), daemon=True).start()
server.serve_forever()
