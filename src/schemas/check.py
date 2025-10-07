from datetime import date, time
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, UUID4, root_validator
from pydantic import model_validator, conint, confloat, constr

from src.models import StatusEnum

# Кастомные типы с валидацией
PositiveInt = conint(gt=0)
ItemName = constr(min_length=1, max_length=50, strip_whitespace=True)
# Валидация цены до 2 знаков после запятой и диапазона
Sum = confloat(ge=0, le=1_000_000_000)


class ItemRequest(BaseModel):
    item_id: PositiveInt = Field(description="ID товара")
    quantity: conint(gt=0, le=1000) = Field(description="Новое количество товара (от 1 до 1000)")


class AddItemRequest(BaseModel):
    name: ItemName = Field(description="Название товара")
    quantity: PositiveInt = Field(gt=0, le=1000, description="Количество товара (от 1 до 1000)")
    sum: Sum = Field(description="Цена товара")

    # Валидация цены до 2 знаков после запятой
    @field_validator('sum')
    def validate_sum(cls, value: float) -> float:
        if round(value, 2) != value:
            raise ValueError("Цена должна иметь не более 2 знаков после запятой")
        return value


class EditItemRequest(BaseModel):
    id: PositiveInt = Field(description="ID товара")
    name: Optional[ItemName] = Field(None, description="Новое название товара")
    quantity: Optional[PositiveInt] = Field(None, gt=0, le=1000, description="Новое количество товара (от 1 до 1000)")
    sum: Optional[Sum] = Field(None, description="Новая цена товара")

    # Проверка, что хотя бы одно поле заполнено
    @model_validator(mode='after')
    def check_at_least_one_field(cls, model):
        # Проверяем, что хотя бы одно из полей (кроме id) заполнено
        if not any(getattr(model, field) is not None for field in ['name', 'quantity', 'sum']):
            raise ValueError("Необходимо указать хотя бы одно поле для обновления")
        return model


class EditItemRequestV2(BaseModel):
    name: Optional[ItemName] = Field(None, description="Новое название товара")
    quantity: Optional[PositiveInt] = Field(None, le=1000, description="Новое количество (до 1000)")
    sum: Optional[Sum] = Field(None, description="Новая цена товара")

    @model_validator(mode='after')
    def check_at_least_one_field(cls, model):
        if not any(getattr(model, field) is not None for field in ['name', 'quantity', 'sum']):
            raise ValueError("Необходимо указать хотя бы одно поле для обновления")
        return model


class DeleteItemRequest(BaseModel):
    id: PositiveInt = Field(description="ID товара")


class CheckSelectionRequest(BaseModel):
    selected_items: List[ItemRequest] = Field(default_factory=list, description="Список выбранных товаров")


class CheckListResponse(BaseModel):
    uuid: str
    name: str
    author_id: int
    currency: Optional[str] = None
    status: str
    date: str
    total: Optional[Sum]
    restaurant: Optional[str] = None

