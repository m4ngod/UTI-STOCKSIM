"""Transactional persistence for Reproduction Manifests and replay reports."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Mapping, Sequence, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .reproduction import (
    ReproductionManifest,
    ReproductionReport,
    _validate_report_against_manifest,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class SqlReproductionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add_manifests(
        self,
        manifests: Sequence[ReproductionManifest],
    ) -> None:
        with self._engine.begin() as connection:
            for manifest in manifests:
                manifest_view = manifest.to_dict()
                manifest_json = _canonical_json(manifest_view)
                existing = connection.execute(
                    text(
                        "SELECT run_id, evidence_package_id, "
                        "schema_version, numeric_tolerance, "
                        "manifest_content_hash, manifest_json "
                        "FROM diagnostic_reproduction_manifests "
                        "WHERE manifest_id = :manifest_id"
                    ),
                    {"manifest_id": manifest.manifest_id},
                ).mappings().one_or_none()
                if existing is not None:
                    if (
                        str(existing["run_id"]) != manifest.run_id
                        or str(existing["evidence_package_id"])
                        != manifest.evidence_package_id
                        or str(existing["schema_version"])
                        != str(manifest_view["schema_version"])
                        or str(existing["numeric_tolerance"])
                        != str(manifest_view["numeric_tolerance"])
                        or str(existing["manifest_content_hash"])
                        != manifest.manifest_content_hash
                        or str(existing["manifest_json"]) != manifest_json
                    ):
                        raise ValueError(
                            "Reproduction Manifest identity collision"
                        )
                    continue
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_reproduction_manifests ("
                        "manifest_id, run_id, evidence_package_id, "
                        "schema_version, numeric_tolerance, "
                        "manifest_content_hash, manifest_json"
                        ") VALUES ("
                        ":manifest_id, :run_id, :evidence_package_id, "
                        ":schema_version, :numeric_tolerance, "
                        ":manifest_content_hash, :manifest_json)"
                    ),
                    {
                        "manifest_id": manifest.manifest_id,
                        "run_id": manifest.run_id,
                        "evidence_package_id": (
                            manifest.evidence_package_id
                        ),
                        "schema_version": str(
                            manifest_view["schema_version"]
                        ),
                        "numeric_tolerance": str(
                            manifest_view["numeric_tolerance"]
                        ),
                        "manifest_content_hash": (
                            manifest.manifest_content_hash
                        ),
                        "manifest_json": manifest_json,
                    },
                )

    def get_manifest(self, manifest_id: str) -> ReproductionManifest:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT run_id, evidence_package_id, "
                    "schema_version, numeric_tolerance, "
                    "manifest_content_hash, manifest_json "
                    "FROM diagnostic_reproduction_manifests "
                    "WHERE manifest_id = :manifest_id"
                ),
                {"manifest_id": manifest_id},
            ).mappings().one_or_none()
        if row is None:
            raise KeyError("Unknown Reproduction Manifest")
        payload = json.loads(str(row["manifest_json"]))
        if not isinstance(payload, dict):
            raise ValueError(
                "Persisted Reproduction Manifest must be an object"
            )
        manifest = ReproductionManifest.from_dict(
            cast(Mapping[str, object], payload)
        )
        if (
            manifest.manifest_id != manifest_id
            or manifest.run_id != str(row["run_id"])
            or manifest.evidence_package_id
            != str(row["evidence_package_id"])
            or str(manifest.to_dict()["schema_version"])
            != str(row["schema_version"])
            or str(manifest.to_dict()["numeric_tolerance"])
            != str(row["numeric_tolerance"])
            or manifest.manifest_content_hash
            != str(row["manifest_content_hash"])
        ):
            raise ValueError(
                "Reproduction Manifest row does not match canonical identity"
            )
        return manifest

    def list_manifests(
        self,
        evidence_package_id: str,
    ) -> tuple[ReproductionManifest, ...]:
        with self._engine.connect() as connection:
            ids = connection.execute(
                text(
                    "SELECT manifest_id "
                    "FROM diagnostic_reproduction_manifests "
                    "WHERE evidence_package_id = :evidence_package_id "
                    "ORDER BY manifest_id"
                ),
                {"evidence_package_id": evidence_package_id},
            ).scalars().all()
        return tuple(self.get_manifest(str(value)) for value in ids)

    def manifest_format_identity(
        self,
        evidence_package_id: str,
        manifest_id: str,
    ) -> str | None:
        """Read the format column without parsing a possibly future payload."""

        with self._engine.connect() as connection:
            value = connection.execute(
                text(
                    "SELECT schema_version "
                    "FROM diagnostic_reproduction_manifests "
                    "WHERE manifest_id = :manifest_id "
                    "AND evidence_package_id = :evidence_package_id"
                ),
                {
                    "manifest_id": manifest_id,
                    "evidence_package_id": evidence_package_id,
                },
            ).scalar_one_or_none()
        return None if value is None else str(value)

    def save_report(self, report: ReproductionReport) -> None:
        manifest = self.get_manifest(report.manifest_id)
        _validate_report_against_manifest(report, manifest)
        report_json = _canonical_json(report.to_dict())
        with self._engine.begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT manifest_id, status, report_json "
                    "FROM diagnostic_reproduction_attempts "
                    "WHERE attempt_id = :attempt_id"
                ),
                {"attempt_id": report.attempt_id},
            ).mappings().one_or_none()
            if existing is not None:
                if (
                    str(existing["manifest_id"]) != report.manifest_id
                    or str(existing["status"]) != report.status
                    or str(existing["report_json"]) != report_json
                ):
                    raise ValueError(
                        "Reproduction Report identity collision"
                    )
                connection.execute(
                    text(
                        "UPDATE diagnostic_reproduction_attempts "
                        "SET created_at_utc = :created_at_utc "
                        "WHERE attempt_id = :attempt_id"
                    ),
                    {
                        "attempt_id": report.attempt_id,
                        "created_at_utc": (
                            datetime.now(timezone.utc).isoformat()
                        ),
                    },
                )
                return
            connection.execute(
                text(
                    "INSERT INTO diagnostic_reproduction_attempts ("
                    "attempt_id, manifest_id, status, report_json, "
                    "created_at_utc"
                    ") VALUES ("
                    ":attempt_id, :manifest_id, :status, :report_json, "
                    ":created_at_utc)"
                ),
                {
                    "attempt_id": report.attempt_id,
                    "manifest_id": report.manifest_id,
                    "status": report.status,
                    "report_json": report_json,
                    "created_at_utc": datetime.now(timezone.utc).isoformat(),
                },
            )

    def latest_report(
        self,
        manifest_id: str,
    ) -> ReproductionReport | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT attempt_id, manifest_id, status, report_json "
                    "FROM diagnostic_reproduction_attempts "
                    "WHERE manifest_id = :manifest_id "
                    "ORDER BY created_at_utc DESC, attempt_id DESC LIMIT 1"
                ),
                {"manifest_id": manifest_id},
            ).mappings().one_or_none()
        if row is None:
            return None
        payload = json.loads(str(row["report_json"]))
        if not isinstance(payload, dict):
            raise ValueError(
                "Persisted Reproduction Report must be an object"
            )
        report = ReproductionReport.from_dict(
            cast(Mapping[str, object], payload)
        )
        if (
            report.attempt_id != str(row["attempt_id"])
            or report.manifest_id != manifest_id
            or report.manifest_id != str(row["manifest_id"])
            or report.status != str(row["status"])
        ):
            raise ValueError(
                "Reproduction Report row does not match canonical identity"
            )
        _validate_report_against_manifest(
            report,
            self.get_manifest(manifest_id),
        )
        return report


__all__ = ["SqlReproductionRepository"]
