from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Boolean, DateTime, text
from datetime import datetime
import uuid

class Base(DeclarativeBase):
    pass

class BaseModel(Base):
    __abstract__ = True
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    is_delete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    update_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        server_default=text("now()"), 
        onupdate=datetime.now, 
        nullable=False
    )

# Note: Do not import models here to prevent circular imports.
# Models should be imported in alembic/env.py or when setting up the app metadata.

