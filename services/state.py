# services/state.py — состояние UI (фильтры, выделение) без привязки к Qt.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class AppState:
    """Текущее состояние экрана аналитики."""

    date_from: date | None = None
    date_to: date | None = None
    amount_min_rub: float = 0.0
    amount_max_rub: float | None = None
    hide_hidden_rows: bool = False
    source_filter: str | None = None  # клик по treemap (M2)
    selected: set[str] = field(default_factory=set)  # external_id отмеченных строк
