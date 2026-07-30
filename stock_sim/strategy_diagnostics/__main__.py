"""Command-line entry for the headless diagnostic application."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .application import create_diagnostics_application


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="strategy-diagnostics")
    parser.add_argument(
        "--json",
        action="store_true",
        help="write the application state as JSON",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    state = create_diagnostics_application().start()
    if args.json:
        print(json.dumps(state.to_dict(), sort_keys=True))
    else:
        print(f"{state.product}: {state.message}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
