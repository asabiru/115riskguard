"""Пер-юзерное состояние Telegram-бота.

Держим в памяти последнюю выписку и последний ассессмент, чтобы
кнопки «What-if», «PDF», «Excel» работали без повторной загрузки.
История анализов при этом всё равно пишется в SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..feature_engineering import StatementFeatures
from ..parser import ParseInfo
from ..risk_engine import RiskAssessment


@dataclass
class UserSession:
    """Состояние одного пользователя в боте."""

    df: pd.DataFrame | None = None
    info: ParseInfo | None = None
    features: StatementFeatures | None = None
    assessment: RiskAssessment | None = None
    max_protect: bool = False
    whatif_overrides: dict[str, float] = field(default_factory=dict)


class SessionStore:
    """Потокобезопасное (благодаря asyncio single-thread) хранилище сессий."""

    def __init__(self) -> None:
        self._by_chat: dict[int, UserSession] = {}

    def get(self, chat_id: int) -> UserSession:
        sess = self._by_chat.get(chat_id)
        if sess is None:
            sess = UserSession()
            self._by_chat[chat_id] = sess
        return sess

    def reset(self, chat_id: int) -> None:
        self._by_chat.pop(chat_id, None)
