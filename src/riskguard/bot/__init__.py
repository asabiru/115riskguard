"""Telegram-бот 115RiskGuard на aiogram 3.x.

Запуск:
    python -m riskguard.bot

Необходим переменная окружения ``TELEGRAM_BOT_TOKEN`` с токеном, выданным
@BotFather.  Бот работает в режиме long-polling и не требует публичного
домена — подходит для полностью локального развёртывания.
"""

from .handlers import build_dispatcher, run

__all__ = ["build_dispatcher", "run"]
