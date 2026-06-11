from pydantic import BaseModel, EmailStr, Field
from typing import Any, Generic, TypeVar, Optional
import uuid

from shared.schemas.response import StandardResponse

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")
    first_name: str = Field(..., description="User's first name")
    last_name: str = Field(..., description="User's last name")
    tenant_id: Optional[uuid.UUID] = None


class UserPayload(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: EmailStr
    role: str
    tenant_id: Optional[uuid.UUID] = None


    class Config:
        from_attributes = True





class TokenPayload(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPayload

# Compatibility response models expected by routes
class TokenResponse(TokenPayload):
    """Alias for token response used in auth endpoints."""
    pass

class TokenResponseUser(UserPayload):
    """User info response for /auth/me endpoint."""
    pass



class RefreshTokenRequest(BaseModel):
    refresh_token: str

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, description="New password must be at least 6 characters")
