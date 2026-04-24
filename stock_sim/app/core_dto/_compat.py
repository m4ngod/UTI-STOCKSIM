"""Pydantic v1/v2 compatibility helpers for frontend DTOs."""
from __future__ import annotations

from pydantic import BaseModel as _PydanticBaseModel

try:
    from pydantic import field_validator as field_validator  # type: ignore
    PYDANTIC_V2 = True
except ImportError:  # pragma: no cover - exercised under pydantic v1
    from pydantic import validator as field_validator  # type: ignore
    PYDANTIC_V2 = False


class BaseModel(_PydanticBaseModel):
    """Compat base model that exposes `model_dump()` on pydantic v1."""

    def model_dump(self, *args, **kwargs):
        dump = getattr(super(), "model_dump", None)
        if callable(dump):
            return dump(*args, **kwargs)
        return self.dict(*args, **kwargs)


__all__ = ["BaseModel", "field_validator", "PYDANTIC_V2"]
