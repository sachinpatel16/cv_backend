from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from fastapi import HTTPException, status, Response
from datetime import timedelta
from jose import JWTError

from modules.auth.repository import AuthRepository
from modules.auth.schema import RegisterRequest, LoginRequest, TokenResponse, TokenResponseUser, ChangePasswordRequest, StandardResponse
from shared.utils import security
from configs.base import settings

class AuthService:
    def __init__(self, db: AsyncSession):
        self.repo = AuthRepository(db)
        self.db = db

    async def register(self, response: Response, data: RegisterRequest) -> StandardResponse:
        """Register a new user. Organization creation is removed; only tenant_id (optional) is stored."""
        # 1. Check if email already registered
        existing_user = await self.repo.get_user_by_email(data.email)
        if existing_user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered")
        # 2. Determine tenant_id (create a new one if none provided)
        tenant_id = data.tenant_id
        if tenant_id is None:
            tenant_id = uuid.uuid4()
        # 3. Create user
        password_hash = security.get_password_hash(data.password)
        user = await self.repo.create_user(
            tenant_id=tenant_id,
            first_name=data.first_name,
            last_name=data.last_name,
            email=data.email,
            password_hash=password_hash,
            role="admin",
        )
        await self.db.commit()
        # 3. Generate tokens
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        }
        access_token = security.create_access_token(token_data)
        refresh_token = security.create_refresh_token(token_data)

        # Set HTTP-only cookies
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/"
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=7 * 24 * 60 * 60,  # 7 days
            path="/"
        )

        user_info = TokenResponseUser(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            role=user.role,
            tenant_id=user.tenant_id,
        )
        return StandardResponse(
            message="Registration successful",
            status=status.HTTP_201_CREATED,
            data=user_info,
        )

    async def login(self, response: Response, data: LoginRequest) -> StandardResponse:
        """Authenticate user credentials and return JWT tokens."""
        user = await self.repo.get_user_by_email(data.email)
        if not user or not security.verify_password(data.password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User account is deactivated"
            )

        # Organization lookup removed – only tenant_id is used
        org_name = None
        org_slug = None

        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "tenant_id": str(user.tenant_id) if user.tenant_id else None
        }

        access_token = security.create_access_token(token_data)
        refresh_token = security.create_refresh_token(token_data)

        # Set HTTP-only cookies
        response.set_cookie(
            key="access_token",
            value=access_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/"
        )
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=7 * 24 * 60 * 60,  # 7 days
            path="/"
        )

        user_info = TokenResponseUser(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            role=user.role,
            tenant_id=user.tenant_id,
        )

        return StandardResponse(
            message="Login successful",
            status=status.HTTP_200_OK,
            data=user_info
        )

    async def refresh_tokens(self, response: Response, refresh_token: str) -> StandardResponse:
        """Issue new access and refresh tokens using a valid refresh token."""
        try:
            payload = security.decode_token(refresh_token)
            token_type = payload.get("type")
            if token_type != "refresh":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type"
                )
            
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token payload"
                )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials"
            )

        user = await self.repo.get_user_by_id(user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or deactivated"
            )

        # No organization lookup – tenant_id is stored directly on the user
        org_name = None
        org_slug = None
        token_data = {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role,
            "tenant_id": str(user.tenant_id) if user.tenant_id else None,
            "tenant_slug": org_slug
        }

        new_access_token = security.create_access_token(token_data)
        new_refresh_token = security.create_refresh_token(token_data)

        # Set HTTP-only cookies
        response.set_cookie(
            key="access_token",
            value=new_access_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            path="/"
        )
        response.set_cookie(
            key="refresh_token",
            value=new_refresh_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            max_age=7 * 24 * 60 * 60,  # 7 days
            path="/"
        )

        user_info = TokenResponseUser(
            id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            email=user.email,
            role=user.role,
            tenant_id=user.tenant_id
        )

        return StandardResponse(
            message="Token refreshed",
            status=status.HTTP_200_OK,
            data=user_info
        )

    async def change_password(self, user_id, data: ChangePasswordRequest) -> None:
        """Change password for an authenticated user."""
        user = await self.repo.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        if not security.verify_password(data.old_password, user.password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Incorrect current password"
            )

        user.password = security.get_password_hash(data.new_password)
        await self.db.commit()
