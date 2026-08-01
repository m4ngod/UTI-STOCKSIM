"""Manual Scenario Recipe contracts and lifecycle services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Callable, Iterable, Literal, Mapping, Protocol, cast
from uuid import uuid4

from pydantic import BaseModel, Field, ValidationError

from .historical_segments import HistoricalMarketSegment
from .transformations import (
    ScenarioTransformationCatalog,
    create_initial_transformation_catalog,
)


_SCHEMA_ID = "https://uti-stocksim.local/schema/scenario-recipe-v1.json"
_JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_DECIMAL_WIRE_PATTERN = r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"
_DECIMAL_WIRE_BOUNDS: dict[str, tuple[str, str, bool]] = {
    "commission_bps": ("0", "100", False),
    "slippage_bps": ("0", "1000", False),
    "max_fill_fraction": ("0", "1", True),
}


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _canonical_value(value: object) -> object:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, BaseModel):
        return _canonical_value(value.dict())
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_json(payload: object) -> str:
    return json.dumps(
        _canonical_value(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class _ImmutableRecipeModel(BaseModel):
    class Config:
        allow_mutation = False
        anystr_strip_whitespace = True
        extra = "forbid"


class ExecutionConditionsV1(_ImmutableRecipeModel):
    commission_bps: Decimal = Field(default=Decimal("3"), ge=0, le=100)
    slippage_bps: Decimal = Field(default=Decimal("0"), ge=0, le=1000)
    max_fill_fraction: Decimal = Field(default=Decimal("1"), gt=0, le=1)
    latency_nodes: int = Field(default=0, ge=0, le=120)
    allow_partial_fills: bool = True


class ScenarioTransformationRequestV1(_ImmutableRecipeModel):
    transformation_id: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ScenarioRecipeV1(_ImmutableRecipeModel):
    schema_version: Literal["scenario_recipe.v1"] = "scenario_recipe.v1"
    name: str = Field(min_length=1, max_length=120)
    historical_segment_id: str = Field(min_length=1, max_length=128)
    transformations: tuple[ScenarioTransformationRequestV1, ...] = ()
    execution_conditions: ExecutionConditionsV1 = Field(
        default_factory=ExecutionConditionsV1
    )
    decision_cadence_minutes: Literal[30, 60]
    materialization_seed: int = Field(default=0, ge=0, le=2_147_483_647)
    data_policy: Literal["point-in-time"] = "point-in-time"
    market_rule_profile: Literal["a-share-cash-equity.v1"] = (
        "a-share-cash-equity.v1"
    )

    def canonical_json(self) -> str:
        return _canonical_json(self)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def stable_json_schema(cls) -> dict[str, object]:
        schema = cls.schema()
        schema["$id"] = _SCHEMA_ID
        schema["$schema"] = _JSON_SCHEMA_DIALECT
        definitions = cast(dict[str, object], schema["definitions"])
        execution = cast(
            dict[str, object],
            definitions["ExecutionConditionsV1"],
        )
        properties = cast(dict[str, dict[str, object]], execution["properties"])
        for field, (minimum, maximum, exclusive_minimum) in (
            _DECIMAL_WIRE_BOUNDS.items()
        ):
            original = properties[field]
            wire_schema: dict[str, object] = {
                "title": original["title"],
                "type": "string",
                "pattern": _DECIMAL_WIRE_PATTERN,
                "x-decimal-minimum": minimum,
                "x-decimal-maximum": maximum,
            }
            if exclusive_minimum:
                wire_schema["x-decimal-exclusive-minimum"] = True
            if "default" in original:
                wire_schema["default"] = _decimal_text(
                    Decimal(str(original["default"]))
                )
            properties[field] = wire_schema
        return cast(dict[str, object], json.loads(_canonical_json(schema)))


class TransformationProposalV1(_ImmutableRecipeModel):
    """A retained idea that has no execution authority."""

    schema_version: Literal["transformation_proposal.v1"] = (
        "transformation_proposal.v1"
    )
    capability: str = Field(min_length=1, max_length=128)
    description: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=1000)
    status: Literal["non_executable"] = "non_executable"


class AIRecipeDraftOutputV1(_ImmutableRecipeModel):
    """Model-independent output shared by every recipe-assistant adapter."""

    schema_version: Literal["ai_recipe_draft_output.v1"] = (
        "ai_recipe_draft_output.v1"
    )
    recipe: ScenarioRecipeV1
    transformation_proposals: tuple[TransformationProposalV1, ...] = ()

    def canonical_json(self) -> str:
        return _canonical_json(self)

    def to_dict(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(self.canonical_json()))


class AIRecipeAssistantError(RuntimeError):
    """Expected external-assistant failure safe for authoring audit records."""

    status: Literal["provider_error", "malformed_output"]
    error_code: str

    def __init__(
        self,
        message: str,
        *,
        response_id: str | None = None,
        response_json: str | None = None,
    ) -> None:
        super().__init__(message)
        self.response_id = response_id
        self.response_json = response_json


class AIRecipeAssistantProviderError(AIRecipeAssistantError):
    status = "provider_error"
    error_code = "provider_error"


class AIRecipeAssistantMalformedOutputError(AIRecipeAssistantError):
    status = "malformed_output"
    error_code = "malformed_output"


@dataclass(frozen=True, slots=True)
class AIRecipeAssistantRequest:
    """Everything an adapter may use to translate one authoring intent."""

    intent: str
    scenario_recipe_schema: Mapping[str, object]
    admitted_segments: tuple[Mapping[str, object], ...]
    transformation_catalog: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AIRecipeAssistantResponse:
    response_id: str
    response_json: str
    output: AIRecipeDraftOutputV1


class AIRecipeAssistant(Protocol):
    """True external seam for replaceable recipe-authoring providers."""

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def prompt_template_version(self) -> str: ...

    def draft(
        self,
        request: AIRecipeAssistantRequest,
    ) -> AIRecipeAssistantResponse: ...


@dataclass(frozen=True, slots=True)
class AIRecipeAssistantAttempt:
    attempt_id: str
    intent: str
    author: str
    provider: str
    model: str
    prompt_template_version: str
    response_id: str | None
    response_hash: str | None
    status: Literal[
        "draft_valid",
        "draft_invalid",
        "provider_error",
        "malformed_output",
    ]
    created_at: datetime
    draft_id: str | None = None
    transformation_proposals: tuple[TransformationProposalV1, ...] = ()
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "intent": self.intent,
            "author": self.author,
            "provider": self.provider,
            "model": self.model,
            "prompt_template_version": self.prompt_template_version,
            "response_id": self.response_id,
            "response_hash": self.response_hash,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "draft_id": self.draft_id,
            "transformation_proposals": [
                json.loads(proposal.json())
                for proposal in self.transformation_proposals
            ],
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


@dataclass(frozen=True, slots=True)
class AIRecipeAuthoringResult:
    attempt: AIRecipeAssistantAttempt
    draft: ScenarioRecipeDraft | None
    validation: RecipeValidationResult | None

    @property
    def status(self) -> str:
        return self.attempt.status

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "attempt": self.attempt.to_dict(),
            "draft": self.draft.to_dict() if self.draft is not None else None,
            "validation": (
                self.validation.to_dict()
                if self.validation is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class AIRecipeAuditRecord:
    attempt: AIRecipeAssistantAttempt
    validation: RecipeValidationResult | None
    approval_actor: str | None = None
    approved_at: datetime | None = None
    approved_recipe_hash: str | None = None
    approved_version_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt": self.attempt.to_dict(),
            "validation": (
                self.validation.to_dict()
                if self.validation is not None
                else None
            ),
            "approval_actor": self.approval_actor,
            "approved_at": (
                self.approved_at.isoformat()
                if self.approved_at is not None
                else None
            ),
            "approved_recipe_hash": self.approved_recipe_hash,
            "approved_version_id": self.approved_version_id,
        }


class UnapprovedScenarioRecipeError(ValueError):
    """Raised when a caller tries to use something other than an approved version."""


@dataclass(frozen=True, slots=True)
class ScenarioRecipeDraft:
    draft_id: str
    recipe_id: str
    author: str
    created_at: datetime
    payload_json: str
    based_on_version_id: str | None = None
    status: str = "untrusted"

    @property
    def payload(self) -> dict[str, Any]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ValueError("Scenario Recipe Draft payload must be a JSON object")
        return value

    @property
    def payload_hash(self) -> str:
        return hashlib.sha256(self.payload_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "draft_id": self.draft_id,
            "recipe_id": self.recipe_id,
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "payload": self.payload,
            "payload_hash": self.payload_hash,
            "based_on_version_id": self.based_on_version_id,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class RecipeValidationIssue:
    path: str
    rule: str
    message: str
    correction: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "rule": self.rule,
            "message": self.message,
            "correction": self.correction,
        }


@dataclass(frozen=True, slots=True)
class RecipeValidationResult:
    draft_id: str
    payload_hash: str
    is_valid: bool
    issues: tuple[RecipeValidationIssue, ...]
    recipe_content_hash: str | None
    validated_at: datetime
    validated_recipe: ScenarioRecipeV1 | None

    def to_dict(self) -> dict[str, object]:
        return {
            "draft_id": self.draft_id,
            "payload_hash": self.payload_hash,
            "is_valid": self.is_valid,
            "issues": [issue.to_dict() for issue in self.issues],
            "recipe_content_hash": self.recipe_content_hash,
            "validated_at": self.validated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ApprovedScenarioRecipeVersion:
    version_id: str
    recipe_id: str
    version_number: int
    recipe: ScenarioRecipeV1
    content_hash: str
    author: str
    approval_actor: str
    approved_at: datetime
    validation_result: RecipeValidationResult
    based_on_version_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "version_id": self.version_id,
            "recipe_id": self.recipe_id,
            "version_number": self.version_number,
            "recipe": json.loads(self.recipe.canonical_json()),
            "content_hash": self.content_hash,
            "author": self.author,
            "approval_actor": self.approval_actor,
            "approved_at": self.approved_at.isoformat(),
            "validation": self.validation_result.to_dict(),
            "based_on_version_id": self.based_on_version_id,
        }


class ScenarioRecipeRepository(Protocol):
    def add_ai_attempt(
        self,
        attempt: AIRecipeAssistantAttempt,
    ) -> AIRecipeAssistantAttempt: ...

    def get_ai_attempt(
        self,
        attempt_id: str,
    ) -> AIRecipeAssistantAttempt | None: ...

    def add_draft(self, draft: ScenarioRecipeDraft) -> ScenarioRecipeDraft: ...

    def get_draft(self, draft_id: str) -> ScenarioRecipeDraft | None: ...

    def add_validation(
        self,
        validation: RecipeValidationResult,
    ) -> RecipeValidationResult: ...

    def get_validation(self, draft_id: str) -> RecipeValidationResult | None: ...

    def add_version(
        self,
        version: ApprovedScenarioRecipeVersion,
    ) -> ApprovedScenarioRecipeVersion: ...

    def get_version(
        self,
        version_id: str,
    ) -> ApprovedScenarioRecipeVersion | None: ...

    def list_versions(self, recipe_id: str) -> tuple[ApprovedScenarioRecipeVersion, ...]: ...

    def list_all_versions(self) -> tuple[ApprovedScenarioRecipeVersion, ...]: ...


class InMemoryScenarioRecipeRepository:
    def __init__(self) -> None:
        self._ai_attempts: dict[str, AIRecipeAssistantAttempt] = {}
        self._drafts: dict[str, ScenarioRecipeDraft] = {}
        self._validations: dict[str, RecipeValidationResult] = {}
        self._versions: dict[str, ApprovedScenarioRecipeVersion] = {}

    def add_ai_attempt(
        self,
        attempt: AIRecipeAssistantAttempt,
    ) -> AIRecipeAssistantAttempt:
        existing = self._ai_attempts.get(attempt.attempt_id)
        if existing is not None and existing != attempt:
            raise ValueError("immutable AI Recipe Assistant attempt identity collision")
        self._ai_attempts[attempt.attempt_id] = attempt
        return attempt

    def get_ai_attempt(
        self,
        attempt_id: str,
    ) -> AIRecipeAssistantAttempt | None:
        return self._ai_attempts.get(attempt_id)

    def add_draft(self, draft: ScenarioRecipeDraft) -> ScenarioRecipeDraft:
        existing = self._drafts.get(draft.draft_id)
        if existing is not None and existing != draft:
            raise ValueError("immutable Scenario Recipe Draft identity collision")
        self._drafts[draft.draft_id] = draft
        return draft

    def get_draft(self, draft_id: str) -> ScenarioRecipeDraft | None:
        return self._drafts.get(draft_id)

    def add_validation(
        self,
        validation: RecipeValidationResult,
    ) -> RecipeValidationResult:
        if any(
            version.validation_result.draft_id == validation.draft_id
            for version in self._versions.values()
        ):
            raise ValueError(
                "Validation belongs to an approved immutable Scenario Recipe Version"
            )
        self._validations[validation.draft_id] = validation
        return validation

    def get_validation(self, draft_id: str) -> RecipeValidationResult | None:
        return self._validations.get(draft_id)

    def add_version(
        self,
        version: ApprovedScenarioRecipeVersion,
    ) -> ApprovedScenarioRecipeVersion:
        if any(
            existing.validation_result.draft_id
            == version.validation_result.draft_id
            for existing in self._versions.values()
        ):
            raise ValueError(
                "Scenario Recipe Draft already belongs to an approved immutable version"
            )
        existing = self._versions.get(version.version_id)
        if existing is not None and existing != version:
            raise ValueError("immutable Scenario Recipe Version identity collision")
        self._versions[version.version_id] = version
        return version

    def get_version(
        self,
        version_id: str,
    ) -> ApprovedScenarioRecipeVersion | None:
        return self._versions.get(version_id)

    def list_versions(
        self,
        recipe_id: str,
    ) -> tuple[ApprovedScenarioRecipeVersion, ...]:
        return tuple(
            sorted(
                (
                    version
                    for version in self._versions.values()
                    if version.recipe_id == recipe_id
                ),
                key=lambda item: item.version_number,
            )
        )

    def list_all_versions(self) -> tuple[ApprovedScenarioRecipeVersion, ...]:
        return tuple(
            sorted(
                self._versions.values(),
                key=lambda item: (item.recipe_id, item.version_number),
            )
        )


class RecipeWorkbench:
    """Own the untrusted-draft to immutable-approved-version lifecycle."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        repository: ScenarioRecipeRepository | None = None,
        transformation_catalog: ScenarioTransformationCatalog | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._repository = repository or InMemoryScenarioRecipeRepository()
        self._transformation_catalog = (
            transformation_catalog or create_initial_transformation_catalog()
        )

    def replace_repository(self, repository: ScenarioRecipeRepository) -> None:
        self._repository = repository

    def author_with_ai(
        self,
        intent: str,
        *,
        author: str,
        assistant: AIRecipeAssistant,
        admitted_segments: Iterable[HistoricalMarketSegment],
    ) -> AIRecipeAuthoringResult:
        normalized_intent = intent.strip()
        if not normalized_intent:
            raise ValueError("AI Recipe Assistant intent is required")
        normalized_author = author.strip()
        if not normalized_author:
            raise ValueError("Scenario Recipe Draft author is required")
        segments = tuple(admitted_segments)
        request = AIRecipeAssistantRequest(
            intent=normalized_intent,
            scenario_recipe_schema=ScenarioRecipeV1.stable_json_schema(),
            admitted_segments=tuple(segment.to_dict() for segment in segments),
            transformation_catalog=self._transformation_catalog.to_dict(),
        )
        try:
            response = assistant.draft(request)
        except AIRecipeAssistantError as error:
            response_hash = (
                hashlib.sha256(error.response_json.encode("utf-8")).hexdigest()
                if error.response_json is not None
                else None
            )
            failed_attempt = AIRecipeAssistantAttempt(
                attempt_id=f"ai_recipe_attempt_{uuid4().hex}",
                intent=normalized_intent,
                author=normalized_author,
                provider=assistant.provider,
                model=assistant.model,
                prompt_template_version=assistant.prompt_template_version,
                response_id=error.response_id,
                response_hash=response_hash,
                status=error.status,
                created_at=self._now(),
                error_code=error.error_code,
                error_message=str(error),
            )
            self._repository.add_ai_attempt(failed_attempt)
            return AIRecipeAuthoringResult(
                attempt=failed_attempt,
                draft=None,
                validation=None,
            )
        draft = self.create_draft(
            json.loads(response.output.recipe.canonical_json()),
            author=normalized_author,
        )
        validation = self.validate_draft(
            draft.draft_id,
            admitted_segments=segments,
        )
        created_at = self._now()
        response_hash = hashlib.sha256(
            response.response_json.encode("utf-8")
        ).hexdigest()
        attempt = AIRecipeAssistantAttempt(
            attempt_id=f"ai_recipe_attempt_{uuid4().hex}",
            intent=normalized_intent,
            author=draft.author,
            provider=assistant.provider,
            model=assistant.model,
            prompt_template_version=assistant.prompt_template_version,
            response_id=response.response_id,
            response_hash=response_hash,
            status="draft_valid" if validation.is_valid else "draft_invalid",
            created_at=created_at,
            draft_id=draft.draft_id,
            transformation_proposals=(
                response.output.transformation_proposals
            ),
        )
        self._repository.add_ai_attempt(attempt)
        return AIRecipeAuthoringResult(
            attempt=attempt,
            draft=draft,
            validation=validation,
        )

    def create_draft(
        self,
        payload: Mapping[str, object],
        *,
        author: str,
        recipe_id: str | None = None,
        based_on_version_id: str | None = None,
    ) -> ScenarioRecipeDraft:
        normalized_author = author.strip()
        if not normalized_author:
            raise ValueError("Scenario Recipe Draft author is required")
        created_at = self._now()
        draft = ScenarioRecipeDraft(
            draft_id=f"recipe_draft_{uuid4().hex}",
            recipe_id=recipe_id or f"recipe_{uuid4().hex}",
            author=normalized_author,
            created_at=created_at,
            payload_json=_canonical_json(dict(payload)),
            based_on_version_id=based_on_version_id,
        )
        return self._repository.add_draft(draft)

    def validate_draft(
        self,
        draft_id: str,
        *,
        admitted_segments: Iterable[HistoricalMarketSegment],
    ) -> RecipeValidationResult:
        draft = self.get_draft(draft_id)
        if any(
            version.validation_result.draft_id == draft_id
            for version in self._repository.list_versions(draft.recipe_id)
        ):
            raise ValueError(
                "Scenario Recipe Draft already belongs to an approved immutable version"
            )
        issues: list[RecipeValidationIssue] = []
        recipe: ScenarioRecipeV1 | None = None
        try:
            recipe = ScenarioRecipeV1.parse_obj(draft.payload)
        except ValidationError as error:
            issues.extend(_schema_validation_issues(error))

        if recipe is not None:
            admitted_ids = {segment.segment_id for segment in admitted_segments}
            if recipe.historical_segment_id not in admitted_ids:
                issues.append(
                    RecipeValidationIssue(
                        path="historical_segment_id",
                        rule="data.admitted-segment-required",
                        message="The selected Historical Market Segment is unavailable.",
                        correction="Select a segment from the admitted catalog.",
                    )
                )
            for issue in self._transformation_catalog.validate_requests(
                recipe.transformations,
                market_rule_profile=recipe.market_rule_profile,
                data_policy=recipe.data_policy,
            ):
                issues.append(
                    RecipeValidationIssue(
                        path=issue.path,
                        rule=issue.rule,
                        message=issue.message,
                        correction=issue.correction,
                    )
                )

        is_valid = recipe is not None and not issues
        result = RecipeValidationResult(
            draft_id=draft.draft_id,
            payload_hash=draft.payload_hash,
            is_valid=is_valid,
            issues=tuple(issues),
            recipe_content_hash=recipe.content_hash if is_valid and recipe else None,
            validated_at=self._now(),
            validated_recipe=recipe if is_valid else None,
        )
        return self._repository.add_validation(result)

    def approve_draft(
        self,
        draft_id: str,
        *,
        actor: str,
    ) -> ApprovedScenarioRecipeVersion:
        normalized_actor = actor.strip()
        if not normalized_actor:
            raise ValueError("Approval actor is required")
        draft = self.get_draft(draft_id)
        validation = self._repository.get_validation(draft_id)
        if (
            validation is None
            or not validation.is_valid
            or validation.payload_hash != draft.payload_hash
            or validation.validated_recipe is None
            or validation.recipe_content_hash is None
        ):
            raise UnapprovedScenarioRecipeError(
                "A Scenario Recipe Draft must pass validation before it can be approved"
            )
        existing_versions = self._repository.list_versions(draft.recipe_id)
        if any(
            version.validation_result.draft_id == draft_id
            for version in existing_versions
        ):
            raise ValueError(
                "Scenario Recipe Draft already belongs to an approved immutable version"
            )
        version_number = 1 + max(
            (
                version.version_number
                for version in existing_versions
            ),
            default=0,
        )
        version_identity = _canonical_json(
            {
                "recipe_id": draft.recipe_id,
                "version_number": version_number,
                "content_hash": validation.recipe_content_hash,
            }
        )
        version = ApprovedScenarioRecipeVersion(
            version_id=(
                "recipe_version_"
                + hashlib.sha256(version_identity.encode("utf-8")).hexdigest()
            ),
            recipe_id=draft.recipe_id,
            version_number=version_number,
            recipe=validation.validated_recipe,
            content_hash=validation.recipe_content_hash,
            author=draft.author,
            approval_actor=normalized_actor,
            approved_at=self._now(),
            validation_result=validation,
            based_on_version_id=draft.based_on_version_id,
        )
        return self._repository.add_version(version)

    def revise_version(
        self,
        version_id: str,
        payload: Mapping[str, object],
        *,
        author: str,
    ) -> ScenarioRecipeDraft:
        approved = self.get_version(version_id)
        return self.create_draft(
            payload,
            author=author,
            recipe_id=approved.recipe_id,
            based_on_version_id=approved.version_id,
        )

    def get_draft(self, draft_id: str) -> ScenarioRecipeDraft:
        draft = self._repository.get_draft(draft_id)
        if draft is None:
            raise ValueError(f"Unknown Scenario Recipe Draft: {draft_id}")
        return draft

    def get_ai_audit(self, attempt_id: str) -> AIRecipeAuditRecord:
        attempt = self._repository.get_ai_attempt(attempt_id)
        if attempt is None:
            raise ValueError(f"Unknown AI Recipe Assistant attempt: {attempt_id}")
        if attempt.draft_id is None:
            return AIRecipeAuditRecord(attempt=attempt, validation=None)
        draft = self.get_draft(attempt.draft_id)
        validation = self._repository.get_validation(attempt.draft_id)
        approved_versions = tuple(
            version
            for version in self._repository.list_versions(draft.recipe_id)
            if version.validation_result.draft_id == attempt.draft_id
        )
        if len(approved_versions) > 1:
            raise ValueError("AI Recipe Assistant attempt has multiple approvals")
        if not approved_versions:
            return AIRecipeAuditRecord(
                attempt=attempt,
                validation=validation,
            )
        approved = approved_versions[0]
        return AIRecipeAuditRecord(
            attempt=attempt,
            validation=validation,
            approval_actor=approved.approval_actor,
            approved_at=approved.approved_at,
            approved_recipe_hash=approved.content_hash,
            approved_version_id=approved.version_id,
        )

    def get_version(self, version_id: str) -> ApprovedScenarioRecipeVersion:
        version = self._repository.get_version(version_id)
        if version is None:
            raise UnapprovedScenarioRecipeError(
                "Only an approved Scenario Recipe Version can be materialized"
            )
        return version

    def list_approved_versions(self) -> tuple[ApprovedScenarioRecipeVersion, ...]:
        """Return every immutable approved recipe in canonical order."""

        return self._repository.list_all_versions()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Recipe lifecycle clock must return a timezone-aware value")
        return value


def _schema_validation_issues(error: ValidationError) -> list[RecipeValidationIssue]:
    issues: list[RecipeValidationIssue] = []
    for item in error.errors():
        path = ".".join(str(part) for part in item.get("loc", ())) or "$"
        kind = str(item.get("type", "value_error"))
        if kind == "value_error.extra":
            rule = "schema.unknown-field"
            correction = "Remove the unsupported field and validate the draft again."
        elif path == "data_policy":
            rule = "causality.point-in-time-required"
            correction = "Use data_policy='point-in-time'."
        elif (
            path == "decision_cadence_minutes"
            or path == "materialization_seed"
            or path.startswith("execution_conditions.")
        ):
            rule = "bounds.invalid"
            correction = "Choose a value within the published ScenarioRecipeV1 bounds."
        else:
            rule = "schema.invalid"
            correction = "Correct the field to match the published ScenarioRecipeV1 schema."
        issues.append(
            RecipeValidationIssue(
                path=path,
                rule=rule,
                message=str(item.get("msg", "Invalid recipe field")),
                correction=correction,
            )
        )
    return issues


__all__ = [
    "AIRecipeAssistant",
    "AIRecipeAssistantError",
    "AIRecipeAssistantMalformedOutputError",
    "AIRecipeAssistantAttempt",
    "AIRecipeAssistantProviderError",
    "AIRecipeAssistantRequest",
    "AIRecipeAssistantResponse",
    "AIRecipeAuthoringResult",
    "AIRecipeAuditRecord",
    "AIRecipeDraftOutputV1",
    "ApprovedScenarioRecipeVersion",
    "ExecutionConditionsV1",
    "InMemoryScenarioRecipeRepository",
    "RecipeValidationIssue",
    "RecipeValidationResult",
    "RecipeWorkbench",
    "ScenarioRecipeDraft",
    "ScenarioRecipeRepository",
    "ScenarioRecipeV1",
    "ScenarioTransformationRequestV1",
    "TransformationProposalV1",
    "UnapprovedScenarioRecipeError",
]
