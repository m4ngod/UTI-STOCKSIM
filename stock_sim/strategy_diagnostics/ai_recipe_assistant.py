"""Replaceable adapters for AI-assisted Scenario Recipe authoring."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Mapping, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import ValidationError

from .recipes import (
    AIRecipeAssistantError,
    AIRecipeAssistantMalformedOutputError,
    AIRecipeAssistantProviderError,
    AIRecipeAssistantRequest,
    AIRecipeAssistantResponse,
    AIRecipeDraftOutputV1,
)


_PROMPT_TEMPLATES = {
    "ai-recipe-assistant.v1": (
        "Translate the user's scenario intent into the supplied structured-output "
        "contract. Select exactly one admitted historical segment and only registered "
        "transformations. Put unavailable capabilities in non-executable transformation "
        "proposals. Never emit code, formulas, filesystem paths, approval instructions, "
        "materialization commands, execution commands, or transformation registrations."
    )
}
_DECIMAL_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"


class OpenAIResponsesTransport(Protocol):
    def create_response(
        self,
        request: dict[str, object],
    ) -> Mapping[str, object]: ...


class OpenAIResponsesHTTPTransport:
    """Minimal production transport for the OpenAI Responses REST endpoint."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = "https://api.openai.com/v1/responses",
        timeout_seconds: float = 120.0,
    ) -> None:
        normalized_key = api_key.strip()
        normalized_endpoint = endpoint.strip()
        if not normalized_key:
            raise ValueError("OPENAI_API_KEY is required")
        if not normalized_endpoint:
            raise ValueError("OpenAI Responses endpoint is required")
        if timeout_seconds <= 0:
            raise ValueError("OpenAI Responses timeout must be positive")
        self._api_key = normalized_key
        self._endpoint = normalized_endpoint
        self._timeout_seconds = timeout_seconds

    def create_response(
        self,
        request: dict[str, object],
    ) -> Mapping[str, object]:
        http_request = Request(
            self._endpoint,
            data=_canonical_json(request).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(  # nosec B310 - endpoint is explicit product configuration
                http_request,
                timeout=self._timeout_seconds,
            ) as response:
                payload = response.read()
        except HTTPError as error:
            raise RuntimeError(
                f"OpenAI Responses HTTP request failed with status {error.code}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise RuntimeError("OpenAI Responses HTTP request failed") from error
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("OpenAI Responses returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise RuntimeError("OpenAI Responses returned a non-object payload")
        return cast(dict[str, object], decoded)


class DeterministicFakeAIRecipeAssistant:
    """Deterministic adapter used by contract and application tests."""

    def __init__(
        self,
        *,
        output: AIRecipeDraftOutputV1 | None = None,
        error: AIRecipeAssistantError | None = None,
        model: str = "deterministic-recipe-fixture.v1",
        prompt_template_version: str = "ai-recipe-assistant.v1",
    ) -> None:
        if (output is None) == (error is None):
            raise ValueError(
                "Deterministic fake requires exactly one output or error"
            )
        self._output = output
        self._error = error
        self._model = model
        self._prompt_template_version = prompt_template_version

    @property
    def provider(self) -> str:
        return "deterministic-fake"

    @property
    def model(self) -> str:
        return self._model

    @property
    def prompt_template_version(self) -> str:
        return self._prompt_template_version

    def draft(
        self,
        request: AIRecipeAssistantRequest,
    ) -> AIRecipeAssistantResponse:
        if not request.intent.strip():
            raise ValueError("AI Recipe Assistant intent is required")
        if self._error is not None:
            raise self._error
        if self._output is None:  # pragma: no cover - constructor enforces this
            raise RuntimeError("Deterministic fake has no configured output")
        response_json = json.dumps(
            {
                "output": self._output.to_dict(),
                "request_intent": request.intent,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        response_hash = hashlib.sha256(response_json.encode("utf-8")).hexdigest()
        return AIRecipeAssistantResponse(
            response_id=f"fake_response_{response_hash}",
            response_json=response_json,
            output=self._output,
        )


class OpenAIResponsesRecipeAssistant:
    """Production adapter for OpenAI Responses structured outputs."""

    def __init__(
        self,
        *,
        transport: OpenAIResponsesTransport,
        model: str,
        prompt_template_version: str = "ai-recipe-assistant.v1",
    ) -> None:
        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("OpenAI Recipe Assistant model is required")
        if prompt_template_version not in _PROMPT_TEMPLATES:
            raise ValueError(
                "Unknown AI Recipe Assistant prompt template version: "
                f"{prompt_template_version}"
            )
        self._transport = transport
        self._model = normalized_model
        self._prompt_template_version = prompt_template_version

    @classmethod
    def from_environment(
        cls,
        *,
        model: str | None = None,
        prompt_template_version: str = "ai-recipe-assistant.v1",
    ) -> OpenAIResponsesRecipeAssistant:
        configured_model = (
            model or os.environ.get("STRATEGY_DIAGNOSTICS_AI_MODEL", "")
        ).strip()
        if not configured_model:
            raise ValueError("STRATEGY_DIAGNOSTICS_AI_MODEL is required")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        endpoint = os.environ.get(
            "OPENAI_RESPONSES_URL",
            "https://api.openai.com/v1/responses",
        )
        return cls(
            transport=OpenAIResponsesHTTPTransport(
                api_key=api_key,
                endpoint=endpoint,
            ),
            model=configured_model,
            prompt_template_version=prompt_template_version,
        )

    @property
    def provider(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    @property
    def prompt_template_version(self) -> str:
        return self._prompt_template_version

    def draft(
        self,
        request: AIRecipeAssistantRequest,
    ) -> AIRecipeAssistantResponse:
        intent = request.intent.strip()
        if not intent:
            raise ValueError("AI Recipe Assistant intent is required")
        provider_request: dict[str, object] = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": _PROMPT_TEMPLATES[self.prompt_template_version],
                },
                {
                    "role": "user",
                    "content": _canonical_json(
                        {
                            "intent": intent,
                            "scenario_recipe_schema": request.scenario_recipe_schema,
                            "admitted_segments": request.admitted_segments,
                            "transformation_catalog": request.transformation_catalog,
                        }
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "ai_recipe_draft_output_v1",
                    "strict": True,
                    "schema": _openai_output_schema(
                        request.transformation_catalog,
                        request.admitted_segments,
                    ),
                }
            },
            "store": False,
        }
        try:
            raw_response = self._transport.create_response(provider_request)
        except Exception as error:
            raise AIRecipeAssistantProviderError(
                f"OpenAI Responses request failed: {error}"
            ) from error
        try:
            response_json = _canonical_json(raw_response)
        except (TypeError, ValueError) as error:
            raise AIRecipeAssistantMalformedOutputError(
                "OpenAI Responses payload is not JSON serializable"
            ) from error
        response_id_value = raw_response.get("id")
        response_id = (
            response_id_value if isinstance(response_id_value, str) else None
        )
        try:
            if not response_id:
                raise ValueError("OpenAI Responses payload is missing a response id")
            output_text = _response_output_text(raw_response)
            output_payload = json.loads(output_text)
            _drop_null_transformation_parameters(output_payload)
            output = AIRecipeDraftOutputV1.parse_obj(output_payload)
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as error:
            raise AIRecipeAssistantMalformedOutputError(
                "OpenAI Responses payload is not a valid AI recipe draft",
                response_id=response_id,
                response_json=response_json,
            ) from error
        return AIRecipeAssistantResponse(
            response_id=response_id,
            response_json=response_json,
            output=output,
        )


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _response_output_text(response: Mapping[str, object]) -> str:
    outputs = response.get("output")
    if not isinstance(outputs, list):
        raise ValueError("OpenAI Responses payload has no output list")
    texts: list[str] = []
    for output in outputs:
        if not isinstance(output, dict) or output.get("type") != "message":
            continue
        content = output.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "refusal":
                raise ValueError("OpenAI Recipe Assistant refused the request")
            if item.get("type") == "output_text" and isinstance(
                item.get("text"), str
            ):
                texts.append(cast(str, item["text"]))
    if len(texts) != 1:
        raise ValueError("OpenAI Responses payload must contain one output_text item")
    return texts[0]


def _drop_null_transformation_parameters(payload: object) -> None:
    if not isinstance(payload, dict):
        return
    recipe = payload.get("recipe")
    if not isinstance(recipe, dict):
        return
    transformations = recipe.get("transformations")
    if not isinstance(transformations, list):
        return
    for transformation in transformations:
        if not isinstance(transformation, dict):
            continue
        parameters = transformation.get("parameters")
        if isinstance(parameters, dict):
            transformation["parameters"] = {
                name: value for name, value in parameters.items() if value is not None
            }


def _openai_output_schema(
    transformation_catalog: Mapping[str, object],
    admitted_segments: tuple[Mapping[str, object], ...],
) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "recipe",
            "transformation_proposals",
        ],
        "properties": {
            "schema_version": {
                "type": "string",
                "enum": ["ai_recipe_draft_output.v1"],
            },
            "recipe": _recipe_schema(
                transformation_catalog,
                admitted_segments,
            ),
            "transformation_proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "schema_version",
                        "capability",
                        "description",
                        "rationale",
                        "status",
                    ],
                    "properties": {
                        "schema_version": {
                            "type": "string",
                            "enum": ["transformation_proposal.v1"],
                        },
                        "capability": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                        },
                        "description": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1000,
                        },
                        "rationale": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 1000,
                        },
                        "status": {
                            "type": "string",
                            "enum": ["non_executable"],
                        },
                    },
                },
            },
        },
    }


def _recipe_schema(
    transformation_catalog: Mapping[str, object],
    admitted_segments: tuple[Mapping[str, object], ...],
) -> dict[str, object]:
    segment_ids = sorted(
        {
            segment_id
            for segment in admitted_segments
            if isinstance((segment_id := segment.get("segment_id")), str)
            and segment_id
        }
    )
    if not segment_ids:
        raise ValueError("AI Recipe Assistant requires an admitted segment")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "name",
            "historical_segment_id",
            "transformations",
            "execution_conditions",
            "decision_cadence_minutes",
            "materialization_seed",
            "data_policy",
            "market_rule_profile",
        ],
        "properties": {
            "schema_version": {
                "type": "string",
                "enum": ["scenario_recipe.v1"],
            },
            "name": {"type": "string", "minLength": 1, "maxLength": 120},
            "historical_segment_id": {
                "type": "string",
                "enum": segment_ids,
            },
            "transformations": {
                "type": "array",
                "items": _transformation_items_schema(transformation_catalog),
            },
            "execution_conditions": _execution_conditions_schema(),
            "decision_cadence_minutes": {
                "type": "integer",
                "enum": [30, 60],
            },
            "materialization_seed": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2_147_483_647,
            },
            "data_policy": {
                "type": "string",
                "enum": ["point-in-time"],
            },
            "market_rule_profile": {
                "type": "string",
                "enum": ["a-share-cash-equity.v1"],
            },
        },
    }


def _execution_conditions_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "commission_bps",
            "slippage_bps",
            "max_fill_fraction",
            "latency_nodes",
            "allow_partial_fills",
        ],
        "properties": {
            "commission_bps": {"type": "string", "pattern": _DECIMAL_PATTERN},
            "slippage_bps": {"type": "string", "pattern": _DECIMAL_PATTERN},
            "max_fill_fraction": {"type": "string", "pattern": _DECIMAL_PATTERN},
            "latency_nodes": {
                "type": "integer",
                "minimum": 0,
                "maximum": 120,
            },
            "allow_partial_fills": {"type": "boolean"},
        },
    }


def _transformation_items_schema(
    transformation_catalog: Mapping[str, object],
) -> dict[str, object]:
    entries = transformation_catalog.get("transformations")
    variants: list[dict[str, object]] = []
    if isinstance(entries, list):
        variants.extend(
            _transformation_variant(entry)
            for entry in entries
            if isinstance(entry, dict)
        )
    if not variants:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {},
        }
    if len(variants) == 1:
        return variants[0]
    return {"anyOf": variants}


def _transformation_variant(entry: Mapping[str, object]) -> dict[str, object]:
    transformation_id = entry.get("transformation_id")
    if not isinstance(transformation_id, str) or not transformation_id:
        raise ValueError("Transformation Catalog entry is missing its identifier")
    raw_parameters = entry.get("parameters")
    parameter_properties: dict[str, object] = {}
    parameter_names: list[str] = []
    if isinstance(raw_parameters, list):
        for raw_parameter in raw_parameters:
            if not isinstance(raw_parameter, dict):
                raise ValueError("Transformation parameter definition must be an object")
            name = raw_parameter.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError(
                    "Transformation parameter definition is missing its name"
                )
            parameter_schema = _parameter_schema(raw_parameter)
            if not bool(raw_parameter.get("required")):
                parameter_schema = {
                    "anyOf": [parameter_schema, {"type": "null"}]
                }
            parameter_properties[name] = parameter_schema
            parameter_names.append(name)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["transformation_id", "parameters"],
        "properties": {
            "transformation_id": {
                "type": "string",
                "enum": [transformation_id],
            },
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "required": parameter_names,
                "properties": parameter_properties,
            },
        },
    }


def _parameter_schema(parameter: Mapping[str, object]) -> dict[str, object]:
    value_type = parameter.get("value_type")
    if value_type == "enum":
        choices = parameter.get("choices")
        if not isinstance(choices, list) or not all(
            isinstance(choice, str) for choice in choices
        ):
            raise ValueError("Enum transformation parameter has invalid choices")
        return {"type": "string", "enum": choices}
    if value_type == "decimal":
        return {"type": "string", "pattern": _DECIMAL_PATTERN}
    raise ValueError(f"Unsupported transformation parameter type: {value_type!r}")


__all__ = [
    "DeterministicFakeAIRecipeAssistant",
    "OpenAIResponsesRecipeAssistant",
    "OpenAIResponsesHTTPTransport",
    "OpenAIResponsesTransport",
]
