import enum
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy import ForeignKey, UniqueConstraint, Enum, String, Float, ForeignKeyConstraint, SmallInteger
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.models.associations import user_check_association


class CheckItem(Base):
    __tablename__ = "check_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    check_uuid: Mapped[str] = mapped_column(ForeignKey("checks.uuid", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[int] = mapped_column(nullable=False)  # Порядковый номер товара
    name: Mapped[str] = mapped_column(nullable=False)     # Наименование товара
    quantity: Mapped[int] = mapped_column(nullable=False)  # Количество
    sum: Mapped[float] = mapped_column(nullable=False)      # Общая сумма за товар

    # Связь с чеком
    check: Mapped["Check"] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint('check_uuid', 'item_id', name='uq_check_item'),
    )

    def __repr__(self) -> str:
        return f"CheckItem(id={self.id}, check_uuid={self.check_uuid}, name={self.name})"


class StatusEnum(enum.Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class RecognitionStatus(enum.IntEnum):
    """
    Числовые коды статуса распознавания (хранятся в БД как SMALLINT).
    """
    NEW = 0              # запись создана, распознавание ещё не началось
    RECOGNIZING = 1      # идёт распознавание
    RECOGNIZED = 2       # успешно распознано и JSON записан
    ERROR = 3            # общий аварийный статус (на всякий случай)
    ERROR_HUGGING = 4    # ошибка/запрет на этапе classifier_image (hugging)
    ERROR_ANTROPIC = 5   # ошибка/нет JSON на этапе Anthropic


class Check(Base):
    __tablename__ = "checks"
    uuid: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=True)

    recognition_status: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=RecognitionStatus.NEW,
    )

    restaurant: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    table_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    order_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Формат "ДД.ММ.ГГГГ", можно заменить на Date
    time: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # Формат "ЧЧ:ММ", можно заменить на Time
    waiter: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    subtotal: Mapped[float] = mapped_column(Float, nullable=True)  # Промежуточный итог
    total: Mapped[float] = mapped_column(Float, nullable=True)  # Итоговая сумма
    currency: Mapped[Optional[str]] = mapped_column(String(3),
                                                    nullable=True)  # Валюта в формате ISO 4217, например "USD"

    # Сервисный сбор
    service_charge_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    service_charge_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    service_charge_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # НДС
    vat_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Ставка НДС
    vat_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Сумма НДС

    # Скидка
    discount_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    check_data: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    error_comment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[StatusEnum] = mapped_column(Enum(StatusEnum), default=StatusEnum.OPEN)
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.now,
        onupdate=datetime.now
    )
    # Relationships
    author: Mapped["User"] = relationship(
        "User",
        foreign_keys="Check.author_id",
        back_populates="authored_checks"
    )

    users: Mapped[List["User"]] = relationship(
        secondary=user_check_association,
        back_populates="checks",
        cascade="all, delete"
    )
    user_selections: Mapped[List["UserSelection"]] = relationship(
        back_populates="check",
        cascade="all, delete-orphan"
    )
    items: Mapped[List["CheckItem"]] = relationship(
        back_populates="check",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"Check(uuid={self.uuid})"


# @event.listens_for(Check, 'before_insert')
# def generate_name(mapper, connection, target):
#     # Генерируем имя по шаблону "check_created_at_первая часть uuid до тире"
#     if target.created_at is None:
#         target.created_at = datetime.now()
#     created_at_str = target.created_at.strftime('%Y%m%d')
#     uuid_part = target.uuid.split('-')[0]
#     # Получаем имя ресторана из check_data, если оно существует.
#     restaurant_name = target.check_data.get('restaurant', '')
#     if restaurant_name:  # Если имя ресторана не пустое
#         target.name = f"{restaurant_name}_{created_at_str}_{uuid_part}"
#     else:
#         target.name = f"check_{created_at_str}_{uuid_part}"


class UserSelection(Base):
    __tablename__ = "user_selections"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True
    )
    check_uuid: Mapped[str] = mapped_column(
        ForeignKey("checks.uuid", ondelete="CASCADE"),
        primary_key=True
    )
    selection: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.now,
        onupdate=datetime.now
    )
    # Relationships
    user: Mapped["User"] = relationship(back_populates="user_selections")
    check: Mapped[Check] = relationship(back_populates="user_selections")
    selected_items: Mapped[List["SelectedItem"]] = relationship(
        "SelectedItem",
        back_populates="user_selection",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            'user_id',
            'check_uuid',
            name='uq_user_selection_user_check'
        ),
    )

    def __repr__(self) -> str:
        return f"UserSelection(user_id={self.user_id}, check_uuid={self.check_uuid})"


class SelectedItem(Base):
    __tablename__ = "selected_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_selection_user_id: Mapped[int] = mapped_column()
    user_selection_check_uuid: Mapped[str] = mapped_column()
    item_id: Mapped[int] = mapped_column()
    quantity: Mapped[int] = mapped_column()

    __table_args__ = (
        ForeignKeyConstraint(
            ['user_selection_user_id', 'user_selection_check_uuid'],
            ['user_selections.user_id', 'user_selections.check_uuid'],
            ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ['user_selection_check_uuid', 'item_id'],
            ['check_items.check_uuid', 'check_items.item_id']
        ),
        UniqueConstraint(
            'user_selection_user_id',
            'user_selection_check_uuid',
            'item_id',
            name='uq_selected_item'
        ),
    )

    user_selection: Mapped["UserSelection"] = relationship(
        "UserSelection",
        back_populates="selected_items"
    )
    check_item: Mapped["CheckItem"] = relationship(
        "CheckItem",
        primaryjoin="and_(SelectedItem.user_selection_check_uuid == CheckItem.check_uuid, SelectedItem.item_id == CheckItem.item_id)"
    )