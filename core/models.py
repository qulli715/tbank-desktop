# core/models.py — версия 0.0.15
# Доменная модель пополнения (входящего перевода). Pydantic v2.

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


class Income(BaseModel):
    """Одно входящее пополнение.

    Все денежные суммы хранятся в копейках (int), время — в UTC (tz-aware).
    """

    external_id: str  # id операции из банка (ключ дедупликации)
    occurred_at: datetime  # время операции, всегда UTC (tz-aware)
    amount_kopecks: int  # сумма в копейках, строго > 0
    currency: str = "RUB"  # ISO-код валюты
    description: str  # сырое описание операции
    category: Optional[str] = None  # category.name
    source: str  # вычисленный источник для pie-чарта
    group: Optional[str] = None  # "INCOME" | "PAY" | "TRANSFER" | None
    account_id: Optional[str] = None
    raw_json: str  # сырая операция, сериализованная в JSON
    is_hidden: bool = False
    hidden_at: Optional[datetime] = None
    inserted_at: datetime  # когда записали в БД (UTC)

    @field_validator("amount_kopecks")
    @classmethod
    def _amount_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("amount_kopecks должен быть > 0")
        return value

    @field_validator("occurred_at", "inserted_at", "hidden_at", mode="before")
    @classmethod
    def _ensure_utc(cls, value):
        """Приводит время к tz-aware UTC; naive считается UTC (с warning)."""
        if value is None:
            return value
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            logger.warning("Naive datetime %r принят как UTC", value)
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
