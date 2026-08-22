"""Loopback-only launcher and file bridge for the hardware library editor."""

from __future__ import annotations

import json
import os
import tempfile
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from hardware_library import HardwareLibrary, HardwareLibraryError


ROOT = Path(__file__).resolve().parent
EDITOR_PATH = ROOT / "hardware_library_editor.html"
LIBRARY_PATH = ROOT / "hardware_library.json"
MAX_LIBRARY_BYTES = 1_000_000


class EditorHandler(BaseHTTPRequestHandler):
    server_version = "HeatInsertLibraryEditor/1.0"

    def _path(self) -> str:
        return urlparse(self.path).path

    def _send(self, status: HTTPStatus, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        path = self._path()
        if path in ("/", "/hardware_library_editor.html"):
            self._send(HTTPStatus.OK, EDITOR_PATH.read_bytes(), "text/html; charset=utf-8")
        elif path == "/hardware_library.json":
            self._send(HTTPStatus.OK, LIBRARY_PATH.read_bytes(), "application/json; charset=utf-8")
        else:
            self._send(HTTPStatus.NOT_FOUND, b"Not found\n", "text/plain; charset=utf-8")

    def do_PUT(self) -> None:
        if self._path() != "/hardware_library.json":
            self._send(HTTPStatus.NOT_FOUND, b"Not found\n", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 2 or length > MAX_LIBRARY_BYTES:
            self._send(HTTPStatus.BAD_REQUEST, b"Invalid file size\n", "text/plain; charset=utf-8")
            return
        payload = self.rfile.read(length)
        temp_path = None
        try:
            parsed = json.loads(payload.decode("utf-8"))
            normalized = (json.dumps(parsed, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix="hardware_library_", suffix=".json", dir=ROOT, delete=False
            ) as temp_file:
                temp_file.write(normalized)
                temp_path = Path(temp_file.name)
            HardwareLibrary.from_path(temp_path)
            os.replace(temp_path, LIBRARY_PATH)
            temp_path = None
            self._send(HTTPStatus.OK, b'{"saved":true}\n', "application/json; charset=utf-8")
        except (UnicodeDecodeError, json.JSONDecodeError, HardwareLibraryError, ValueError) as error:
            message = json.dumps({"saved": False, "error": str(error)}).encode("utf-8")
            self._send(HTTPStatus.BAD_REQUEST, message, "application/json; charset=utf-8")
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink()

    def log_message(self, format_string: str, *args) -> None:
        print("[hardware-library-editor] " + format_string % args, flush=True)


def main() -> None:
    if not EDITOR_PATH.is_file() or not LIBRARY_PATH.is_file():
        raise SystemExit("Editor or hardware_library.json is missing from this folder.")
    server = ThreadingHTTPServer(("127.0.0.1", 0), EditorHandler)
    url = f"http://127.0.0.1:{server.server_port}/hardware_library_editor.html"
    print("Threaded Insert Hardware Library Editor")
    print(f"Serving only this folder on {url}")
    print("Close this window or press Ctrl+C to stop.\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
