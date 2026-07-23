"""Persistence adapters for sealed Diagnostic Evidence packages."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping, Sequence, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .diagnostic_evidence import (
    DiagnosticEvidenceArtifactStore,
    DiagnosticEvidencePackage,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _validate_artifact_hash(artifact_hash: str) -> None:
    if len(artifact_hash) != 64 or any(
        character not in "0123456789abcdef" for character in artifact_hash
    ):
        raise ValueError("artifact hash must be lowercase SHA-256")


class InMemoryDiagnosticEvidenceArtifactStore:
    def __init__(self) -> None:
        self._artifacts: dict[str, dict[str, object]] = {}

    def put(self, payload: Mapping[str, object]) -> str:
        value = json.loads(_canonical_json(dict(payload)))
        if not isinstance(value, dict):
            raise ValueError("Diagnostic Evidence artifact must be an object")
        artifact = cast(dict[str, object], value)
        artifact_hash = _canonical_hash(artifact)
        existing = self._artifacts.get(artifact_hash)
        if existing is not None and existing != artifact:
            raise ValueError("Diagnostic Evidence artifact identity collision")
        self._artifacts[artifact_hash] = artifact
        return artifact_hash

    def get(self, artifact_hash: str) -> dict[str, object]:
        _validate_artifact_hash(artifact_hash)
        try:
            artifact = self._artifacts[artifact_hash]
        except KeyError as error:
            raise KeyError("Unknown Diagnostic Evidence artifact") from error
        if _canonical_hash(artifact) != artifact_hash:
            raise ValueError(
                "Diagnostic Evidence artifact failed hash verification"
            )
        return cast(
            dict[str, object],
            json.loads(_canonical_json(artifact)),
        )


class JsonDiagnosticEvidenceArtifactStore:
    """Atomic content-addressed JSON adapter for bounded evidence packages."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @classmethod
    def from_environment(cls) -> "JsonDiagnosticEvidenceArtifactStore":
        configured = os.environ.get(
            "STOCK_SIM_DIAGNOSTICS_EVIDENCE_ROOT",
            "",
        ).strip()
        if configured:
            root = Path(configured)
        else:
            local_data = Path(
                os.environ.get("LOCALAPPDATA", tempfile.gettempdir())
            )
            root = local_data / "UTI-STOCKSIM" / "diagnostics" / "evidence"
        return cls(root)

    def put(self, payload: Mapping[str, object]) -> str:
        artifact = cast(
            dict[str, object],
            json.loads(_canonical_json(dict(payload))),
        )
        artifact_hash = _canonical_hash(artifact)
        self._root.mkdir(parents=True, exist_ok=True)
        destination = self._artifact_path(artifact_hash)
        if destination.is_file():
            if self.get(artifact_hash) != artifact:
                raise ValueError("Diagnostic Evidence artifact identity collision")
            return artifact_hash
        handle, temporary_name = tempfile.mkstemp(
            prefix=".staging-",
            suffix=".json",
            dir=self._root,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(_canonical_json(artifact))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                temporary.replace(destination)
            except FileExistsError:
                if self.get(artifact_hash) != artifact:
                    raise ValueError(
                        "Diagnostic Evidence artifact identity collision"
                    )
        finally:
            if temporary.exists():
                temporary.unlink()
        return artifact_hash

    def get(self, artifact_hash: str) -> dict[str, object]:
        path = self._artifact_path(artifact_hash)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise KeyError("Unknown Diagnostic Evidence artifact") from error
        if not isinstance(value, dict):
            raise ValueError("Diagnostic Evidence artifact must be an object")
        artifact = cast(dict[str, object], value)
        if _canonical_hash(artifact) != artifact_hash:
            raise ValueError(
                "Diagnostic Evidence artifact failed hash verification"
            )
        return artifact

    def _artifact_path(self, artifact_hash: str) -> Path:
        _validate_artifact_hash(artifact_hash)
        return self._root / f"{artifact_hash}.json"


class SqlDiagnosticEvidenceRepository:
    """Transactional evidence index; large sealed payloads remain artifacts."""

    def __init__(
        self,
        engine: Engine,
        artifact_store: DiagnosticEvidenceArtifactStore,
    ) -> None:
        self._engine = engine
        self._artifact_store = artifact_store

    def add(self, package: DiagnosticEvidencePackage) -> None:
        package.validate_artifacts(self._artifact_store)
        payload = package.sealed_payload()
        with self._engine.begin() as connection:
            existing_hash = connection.execute(
                text(
                    "SELECT artifact_hash FROM diagnostic_evidence_packages "
                    "WHERE evidence_package_id = :evidence_package_id"
                ),
                {"evidence_package_id": package.evidence_package_id},
            ).scalar_one_or_none()
            if existing_hash is not None:
                if str(existing_hash) != package.artifact_hash:
                    raise ValueError("Diagnostic Evidence identity collision")
                return
            for profile_value in cast(
                Sequence[object],
                payload["guardrail_profiles"],
            ):
                profile = cast(Mapping[str, object], profile_value)
                profile_id = str(profile["profile_id"])
                stored_profile = connection.execute(
                    text(
                        "SELECT profile_json FROM diagnostic_guardrail_profiles "
                        "WHERE profile_id = :profile_id"
                    ),
                    {"profile_id": profile_id},
                ).scalar_one_or_none()
                profile_json = _canonical_json(dict(profile))
                if (
                    stored_profile is not None
                    and str(stored_profile) != profile_json
                ):
                    raise ValueError("Strategy Guardrail Profile identity collision")
                if stored_profile is None:
                    connection.execute(
                        text(
                            "INSERT INTO diagnostic_guardrail_profiles ("
                            "profile_id, strategy_id, strategy_version, "
                            "profile_version, profile_json"
                            ") VALUES ("
                            ":profile_id, :strategy_id, :strategy_version, "
                            ":profile_version, :profile_json)"
                        ),
                        {
                            "profile_id": profile_id,
                            "strategy_id": str(profile["strategy_id"]),
                            "strategy_version": str(
                                profile["strategy_version"]
                            ),
                            "profile_version": str(
                                profile["profile_version"]
                            ),
                            "profile_json": profile_json,
                        },
                    )
            connection.execute(
                text(
                    "INSERT INTO diagnostic_evidence_packages ("
                    "evidence_package_id, campaign_id, schema_version, status, "
                    "measurement_artifact_hash, artifact_hash"
                    ") VALUES ("
                    ":evidence_package_id, :campaign_id, :schema_version, "
                    ":status, :measurement_artifact_hash, :artifact_hash)"
                ),
                {
                    "evidence_package_id": package.evidence_package_id,
                    "campaign_id": package.campaign_id,
                    "schema_version": str(payload["schema_version"]),
                    "status": str(payload["status"]),
                    "measurement_artifact_hash": str(
                        payload["measurement_artifact_hash"]
                    ),
                    "artifact_hash": package.artifact_hash,
                },
            )
            for finding_value in cast(
                Sequence[object],
                payload["diagnostic_findings"],
            ):
                finding = cast(Mapping[str, object], finding_value)
                connection.execute(
                    text(
                        "INSERT INTO diagnostic_findings ("
                        "finding_id, evidence_package_id, strategy_id, "
                        "finding_kind, finding_json"
                        ") VALUES ("
                        ":finding_id, :evidence_package_id, :strategy_id, "
                        ":finding_kind, :finding_json)"
                    ),
                    {
                        "finding_id": str(finding["finding_id"]),
                        "evidence_package_id": package.evidence_package_id,
                        "strategy_id": str(finding["strategy_id"]),
                        "finding_kind": str(finding["kind"]),
                        "finding_json": _canonical_json(dict(finding)),
                    },
                )

    def get(self, evidence_package_id: str) -> DiagnosticEvidencePackage | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT campaign_id, schema_version, status, "
                    "measurement_artifact_hash, artifact_hash "
                    "FROM diagnostic_evidence_packages "
                    "WHERE evidence_package_id = :evidence_package_id"
                ),
                {"evidence_package_id": evidence_package_id},
            ).mappings().one_or_none()
        if row is None:
            return None
        value = str(row["artifact_hash"])
        payload = self._artifact_store.get(value)
        package = DiagnosticEvidencePackage.from_payload(payload, value)
        if (
            package.evidence_package_id != evidence_package_id
            or str(row["campaign_id"]) != package.campaign_id
            or str(row["schema_version"]) != str(payload["schema_version"])
            or str(row["status"]) != str(payload["status"])
            or str(row["measurement_artifact_hash"])
            != str(payload["measurement_artifact_hash"])
        ):
            raise ValueError(
                "Diagnostic Evidence index does not match artifact identity"
            )
        package.validate_artifacts(self._artifact_store)
        return package


__all__ = [
    "InMemoryDiagnosticEvidenceArtifactStore",
    "JsonDiagnosticEvidenceArtifactStore",
    "SqlDiagnosticEvidenceRepository",
]
