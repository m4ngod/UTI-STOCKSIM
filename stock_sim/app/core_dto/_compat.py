"""Pydantic v1/v2 compatibility helpers for frontend DTOs."""
from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel as _PydanticBaseModel

try:
    from pydantic import field_validator as field_validator
    PYDANTIC_V2 = True
except ImportError:  # pragma: no cover - exercised under pydantic v1
    from pydantic import validator as field_validator
    PYDANTIC_V2 = False


class BaseModel(_PydanticBaseModel):  # type: ignore[misc]
    """Compat base model that exposes ``model_dump()`` on pydantic v1."""

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        dump = getattr(super(), "model_dump", None)
        if callable(dump):
            return cast(dict[str, Any], dump(*args, **kwargs))
        return cast(dict[str, Any], self.dict(*args, **kwargs))


__all__ = ["BaseModel", "field_validator", "PYDANTIC_V2"]
