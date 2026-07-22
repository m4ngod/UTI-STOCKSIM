"""UTF-8 JSON entry point for one isolated PTrade host invocation."""

from __future__ import annotations

import sys

from .ptrade_host import subprocess_worker_response


def main() -> int:
    request_text = sys.stdin.read()
    sys.stdout.write(subprocess_worker_response(request_text))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess host
    raise SystemExit(main())
