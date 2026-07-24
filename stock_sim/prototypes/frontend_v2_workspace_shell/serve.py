"""THROWAWAY PROTOTYPE server for Frontend V2 workspace shell issue #30."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from functools import partial


HOST = "127.0.0.1"
PORT = 4173
ROOT = Path(__file__).resolve().parent


if __name__ == "__main__":
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"Frontend V2 shell prototype: http://{HOST}:{PORT}/?variant=A")
    print("Press Ctrl+C to stop.")
    server.serve_forever()
