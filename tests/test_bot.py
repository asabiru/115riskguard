"""Smoke-тесты Telegram-бота (aiogram 3.x).

Живого запроса к Telegram API не делаем. Проверяем:
* dispatcher собирается и регистрирует все нужные хэндлеры
* клавиатуры строятся и содержат корректные callback_data
* форматирование итога анализа / списка флагов не падает
"""

from __future__ import annotations

import pytest

from riskguard.bot import handlers
from riskguard.bot.keyboards import (
    after_analysis,
    back_to_menu,
    history_list,
    main_menu,
    whatif_menu,
)
from riskguard.bot.session import SessionStore, UserSession
from riskguard.feature_engineering import compute_features
from riskguard.parser import parse_statement
from riskguard.risk_engine import assess_risk


def _sample_assessment():
    df, info = parse_statement("sample_data/tinkoff_sample.csv")
    feat = compute_features(df)
    assess = assess_risk(feat)
    return df, info, feat, assess


def test_build_dispatcher_registers_handlers():
    dp = handlers.build_dispatcher()
    assert dp is not None
    # два базовых observer'а обязаны иметь хоть один хэндлер
    assert any(dp.message.handlers), "нет message-хэндлеров"
    assert any(dp.callback_query.handlers), "нет callback_query-хэндлеров"


def test_keyboards_have_expected_callbacks():
    callbacks = {b.callback_data for row in main_menu().inline_keyboard for b in row}
    expected = {"upload", "last", "whatif", "history", "toggle_protect", "help"}
    assert expected.issubset(callbacks)

    whatif_cbs = {b.callback_data for row in whatif_menu().inline_keyboard for b in row}
    assert {"wi:p2p:20", "wi:crypto:10", "wi:cash:0.3", "wi:reset", "menu"}.issubset(
        whatif_cbs
    )

    after_cbs = {b.callback_data for row in after_analysis().inline_keyboard for b in row}
    assert {"report_pdf", "report_xlsx", "whatif", "flags_all", "menu"}.issubset(after_cbs)

    assert any(b.callback_data == "menu" for row in back_to_menu().inline_keyboard for b in row)


def test_history_list_renders_items():
    items = [
        {"id": 1, "created_at": "2026-04-20T10:00:00", "level": "red", "risk_score": 80, "bank": "Т-Банк"},
        {"id": 2, "created_at": "2026-04-21T11:00:00", "level": "green", "risk_score": 10, "bank": "Сбер"},
    ]
    kb = history_list(items)
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("🔴" in t for t in texts)
    assert any("🟢" in t for t in texts)
    assert any(
        b.callback_data == "hist:1" for row in kb.inline_keyboard for b in row
    )


def test_format_assessment_uses_level_emoji():
    _, info, feat, assess = _sample_assessment()
    text = handlers._format_assessment(
        assess, bank=info.bank, rows_parsed=info.rows_parsed, max_protect=False
    )
    assert f"{assess.risk_score:.0f}/100" in text
    assert any(emoji in text for emoji in ("🟢", "🟡", "🔴"))


def test_format_all_flags_splits_into_chunks():
    _, _, _, assess = _sample_assessment()
    chunks = handlers._format_all_flags(assess)
    assert chunks
    for chunk in chunks:
        assert len(chunk) <= 4000


def test_session_store_per_chat():
    store = SessionStore()
    a = store.get(1)
    a.max_protect = True
    b = store.get(2)
    assert isinstance(a, UserSession)
    assert b.max_protect is False
    assert store.get(1).max_protect is True


@pytest.mark.asyncio
async def test_run_requires_token(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        await handlers.run()
