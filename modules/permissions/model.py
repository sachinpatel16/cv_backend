import uuid
from sqlalchemy import String, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from database.base import BaseModel

class UserPermission(BaseModel):
    __tablename__ = "user_permissions"
    
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., "cameras.view"
    granted: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
