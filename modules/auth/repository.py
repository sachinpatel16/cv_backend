from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from modules.users.model import User

from modules.permissions.model import UserPermission

class AuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_email(self, email: str) -> User | None:
        """Fetch a user by their email address, including organization relation."""
        stmt = select(User).where(User.email == email, User.is_delete == False)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_user_by_id(self, user_id) -> User | None:
        """Fetch a user by their unique ID."""
        stmt = select(User).where(User.id == user_id, User.is_delete == False)
        result = await self.db.execute(stmt)
        return result.scalars().first()





    async def create_user(self, tenant_id, first_name: str, last_name: str, email: str, password_hash: str, role: str) -> User:
        """Create a new user under a tenant."""
        user = User(tenant_id=tenant_id, first_name=first_name, last_name=last_name, email=email, password=password_hash, role=role)
        self.db.add(user)
        await self.db.flush()  # populate ID
        return user
