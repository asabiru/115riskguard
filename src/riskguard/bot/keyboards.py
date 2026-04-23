"""Инлайн-клавиатуры для Telegram-бота.

Все клавиатуры собираются через :class:`InlineKeyboardBuilder` — это
стандартный способ в aiogram 3.x.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu(max_protect_on: bool = False) -> InlineKeyboardMarkup:
    """Главное меню бота."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Загрузить выписку", callback_data="upload")
    kb.button(text="📊 Последний анализ", callback_data="last")
    kb.button(text="🧪 What-if", callback_data="whatif")
    kb.button(text="📚 История", callback_data="history")
    shield = "🛡 Защита: Макс" if max_protect_on else "🛡 Защита: Стандарт"
    kb.button(text=shield, callback_data="toggle_protect")
    kb.button(text="❓ Помощь", callback_data="help")
    kb.adjust(1, 2, 1, 2)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В меню", callback_data="menu")
    return kb.as_markup()


def after_analysis() -> InlineKeyboardMarkup:
    """Кнопки под сообщением с итогом анализа."""
    kb = InlineKeyboardBuilder()
    kb.button(text="📄 PDF-отчёт", callback_data="report_pdf")
    kb.button(text="📊 Excel-отчёт", callback_data="report_xlsx")
    kb.button(text="🧪 What-if", callback_data="whatif")
    kb.button(text="📝 Все флаги", callback_data="flags_all")
    kb.button(text="⬅️ В меню", callback_data="menu")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def whatif_menu() -> InlineKeyboardMarkup:
    """Кнопки для What-if-сценариев."""
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ 20 P2P за 30 дн.", callback_data="wi:p2p:20")
    kb.button(text="➕ 50 P2P за 30 дн.", callback_data="wi:p2p:50")
    kb.button(text="➕ 10 крипто-операций", callback_data="wi:crypto:10")
    kb.button(text="➕ 30% наличных", callback_data="wi:cash:0.3")
    kb.button(text="➕ 300 000 ₽ поступления", callback_data="wi:income:300000")
    kb.button(text="🔄 Сбросить", callback_data="wi:reset")
    kb.button(text="⬅️ В меню", callback_data="menu")
    kb.adjust(1, 1, 1, 1, 1, 1, 1)
    return kb.as_markup()


def history_list(items: list[dict]) -> InlineKeyboardMarkup:
    """Список последних записей истории (до 10).

    Каждая запись — кликабельная кнопка, callback_data содержит id.
    """
    kb = InlineKeyboardBuilder()
    for it in items[:10]:
        level = (it.get("level") or "green").lower()
        emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(level, "⚪️")
        created = (it.get("created_at") or "")[:16].replace("T", " ")
        score = it.get("risk_score") or 0
        label = f"{emoji} {created} · {int(score)}/100 · {it.get('bank') or '—'}"
        kb.button(text=label, callback_data=f"hist:{it['id']}")
    kb.button(text="⬅️ В меню", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()
