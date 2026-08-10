"""Command-line validator for Wave 4 daily observation ledgers."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import cast

from stock_sim.release.wave4_observation_ledger import (
    LedgerValidationError,
    ObservationWindowError,
    assess_daily_observation_ledger,
    calculate_observation_window,
)


_OUTPUT_SCHEMA_VERSION = "wave4.ledger-validator-output.v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate passive Wave 4 daily observation ledgers.",
    )
    parser.add_argument("ledger", nargs="+", type=Path)
    parser.add_argument("--require-qualifying", action="store_true")
    parser.add_argument("--require-14-days", action="store_true")
    return parser


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _read_payload(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ValueError("ledger input is unreadable") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("ledger input is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("ledger input must be a JSON object")
    return cast(dict[str, object], raw)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        ledgers = [_read_payload(path) for path in arguments.ledger]
        assessments = [
            assess_daily_observation_ledger(ledger) for ledger in ledgers
        ]
        response: dict[str, object] = {
            "schema_version": _OUTPUT_SCHEMA_VERSION,
            "status": "accepted",
            "assessments": [asdict(assessment) for assessment in assessments],
        }
        requirement_satisfied = True
        if arguments.require_14_days:
            window = calculate_observation_window(ledgers)
            response["window"] = asdict(window)
            requirement_satisfied = window.fourteen_day_requirement_satisfied
        qualifying_satisfied = (
            not arguments.require_qualifying
            or all(assessment.qualifying for assessment in assessments)
        )
        if not qualifying_satisfied or not requirement_satisfied:
            response["status"] = "rejected"
            _emit(response)
            return 1
        _emit(response)
        return 0
    except LedgerValidationError as exc:
        _emit(
            {
                "schema_version": _OUTPUT_SCHEMA_VERSION,
                "status": "invalid",
                "error_code": "ledger_validation_error",
                "message": str(exc),
            }
        )
        return 2
    except ObservationWindowError as exc:
        _emit(
            {
                "schema_version": _OUTPUT_SCHEMA_VERSION,
                "status": "invalid",
                "error_code": "observation_window_error",
                "message": str(exc),
            }
        )
        return 2
    except ValueError as exc:
        _emit(
            {
                "schema_version": _OUTPUT_SCHEMA_VERSION,
                "status": "invalid",
                "error_code": "ledger_input_error",
                "message": str(exc),
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
