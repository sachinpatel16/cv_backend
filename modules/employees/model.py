import uuid
from sqlalchemy import String, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY
from pgvector.sqlalchemy import Vector

from database.base import BaseModel

class Employee(BaseModel):
    """
    Stores registered employee profiles for attendance tracking.
    """
    __tablename__ = "employees"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False) # e.g., 'EMP001'
    photo_path: Mapped[str] = mapped_column(String(512), nullable=False)  # Path to registration profile picture

    # Relationships
    embeddings: Mapped[list["EmployeeEmbedding"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )
    attendance_logs: Mapped[list["EmployeeAttendanceLog"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )


class EmployeeEmbedding(BaseModel):
    """
    Stores visual ReID feature vectors of registered employees.
    """
    __tablename__ = "employee_embeddings"

    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False) # 512-dimensional ResNet-18 vector
    bbox: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True) # Bounding box in registration image

    employee: Mapped["Employee"] = relationship(back_populates="embeddings")
