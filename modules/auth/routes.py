from fastapi import APIRouter, Depends, status, Response, Cookie, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from modules.auth.schema import (
    LoginRequest, RegisterRequest, TokenResponse,
    RefreshTokenRequest, ChangePasswordRequest, TokenResponseUser
)
from modules.auth.service import AuthService
from modules.auth.repository import AuthRepository
from shared.dependencies.auth import get_current_user
from modules.users.model import User

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/register", response_model=StandardResponse[TokenResponseUser], status_code=status.HTTP_201_CREATED)
async def register(response: Response, data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new user (optional tenant)."""
    service = AuthService(db)
    return await service.register(response, data)

@router.post("/login", response_model=StandardResponse[TokenResponseUser])
async def login(response: Response, data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate user credentials and return JWT tokens."""
    service = AuthService(db)
    return await service.login(response, data)

@router.post("/refresh", response_model=StandardResponse[TokenResponseUser])
async def refresh(response: Response, refresh_token: str | None = Cookie(None), db: AsyncSession = Depends(get_db)):
    """Refresh access token using refresh token."""
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is missing"
        )
    service = AuthService(db)
    return await service.refresh_tokens(response, refresh_token)

@router.get("/me", response_model=StandardResponse[TokenResponseUser])
async def get_me(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get profile of current authenticated user (tenant only)."""
    user_info = TokenResponseUser(
        id=current_user.id,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        email=current_user.email,
        role=current_user.role,
        tenant_id=current_user.tenant_id,
    )
    return StandardResponse(
        message="User profile retrieved",
        status=status.HTTP_200_OK,
        data=user_info
    )

@router.post("/change-password", response_model=StandardResponse, status_code=status.HTTP_200_OK)
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Change the password for the current authenticated user."""
    service = AuthService(db)
    await service.change_password(current_user.id, data)
    return StandardResponse(
        message="Password updated successfully",
        status=status.HTTP_200_OK,
        data=None
    )

@router.post("/logout", response_model=StandardResponse, status_code=status.HTTP_200_OK)
async def logout(response: Response, current_user: User = Depends(get_current_user)):
    """Stateless logout. Token should be deleted from the client."""
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
    return StandardResponse(
        message="Successfully logged out",
        status=status.HTTP_200_OK,
        data=None
    )
