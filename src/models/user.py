from datetime import datetime
from typing import List

from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.associations import user_check_association


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    hashed_password: Mapped[str]
    is_soft_deleted: Mapped[bool] = mapped_column(default=False)
    soft_deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    is_deleted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.now,
        onupdate=datetime.now
    )
    # Связь с профилем
    profile: Mapped["UserProfile"] = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan"
    )
    authored_checks: Mapped[List["Check"]] = relationship(
        "Check",
        foreign_keys="Check.author_id",
        back_populates="author",
        passive_deletes=True  # Позволяет SQLAlchemy использовать ON DELETE SET NULL
    )
    checks: Mapped[List["Check"]] = relationship(
        secondary=user_check_association,
        back_populates="users",
        cascade="all, delete"
    )
    user_selections: Mapped[List["UserSelection"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )

    def __str__(self) -> str:
        return f"User: {self.email}"

    def __repr__(self) -> str:
        return f"User(id={self.id}, email={self.email})"


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(nullable=True)
    user_message: Mapped[str]
    app_version: Mapped[str]
    device_info: Mapped[str]
    locale: Mapped[str]
    email: Mapped[str] = mapped_column(nullable=True)
    location: Mapped[str]