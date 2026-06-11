from __future__ import annotations

from typing import Generic, TypeVar, Optional

from pydantic import BaseModel, Field

T = TypeVar('T')

class StandardResponse(BaseModel, Generic[T]):
    """A generic wrapper used for all API responses.
    
    Fields:
        message: Human‑readable description of the operation outcome.
        status: HTTP status code (e.g., 200, 201, 400).
        data:    Payload of type ``T`` – can be ``None`` for simple messages.
    """
    message: str = Field(..., description="Human‑readable description")
    status: int = Field(..., description="HTTP status code")
    data: Optional[T] = Field(default=None, description="Response payload")
