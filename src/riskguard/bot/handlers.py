"""Хэндлеры aiogram 3.x для Telegram-бота 115RiskGuard.

Основные команды / кнопки
-------------------------

* ``/start``, ``/help`` — вступление + главное меню
* кнопка «📥 Загрузить выписку» — просит прислать документ
* загрузка документа → парсинг → расчёт риска → сообщение + клавиатура
  «PDF / XLSX / What-if / Все флаги»
* кнопка «🧪 What-if» — набор сценариев с callback_data ``wi:<kind>:<value>``
* кнопка «🛡 Защита» — переключает ``Thresholds.tighten()``
* кнопка «📚 История» — читает SQLite и выдаёт последние записи
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)

from ..constants import DEFAULT_THRESHOLDS, Thresholds
from ..feature_engineering import compute_features
from ..parser import parse_statement
from ..report_generator import build_excel_report, build_pdf_report
from ..risk_engine import (
    RiskAssessment,
    assess_risk,
    whatif_adjust_features,
)
from ..storage import list_analyses, load_analysis, save_analysis
from . import texts as T
from .keyboards import (
    after_analysis,
    back_to_menu,
    history_list,
    main_menu,
    whatif_menu,
)
from .session import SessionStore

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 МБ — с запасом на большие выписки


# ----------------------------- форматирование --------------------------


def _format_assessment(
    assessment: RiskAssessment,
    *,
    bank: str,
    rows_parsed: int,
    max_protect: bool,
) -> str:
    emoji = T.LEVEL_EMOJI.get(assessment.level.value, "⚪️")
    level_label = T.LEVEL_TEXT_RU.get(assessment.level.value, "—")
    red = sum(1 for f in assessment.flags if f.severity == "red")
    yellow = sum(1 for f in assessment.flags if f.severity == "yellow")
    lines = [
        f"{emoji} <b>{level_label} уровень</b> — "
        f"{assessment.risk_score:.0f}/100 "
        f"(вероятность блокировки ≈ {assessment.probability * 100:.0f}%)",
        "",
        f"🏦 Банк: <b>{bank or '—'}</b>",
        f"📊 Операций разобрано: <b>{rows_parsed}</b>",
        f"🔴 Красных флагов: <b>{red}</b> · 🟡 Жёлтых: <b>{yellow}</b>",
    ]
    if max_protect:
        lines.append("🛡 Режим максимальной защиты: <b>включён</b>")
    lines.append("")
    lines.append(_shorten(assessment.summary, 400))

    # топ-3 флага коротко
    top = sorted(assessment.flags, key=lambda f: f.contribution, reverse=True)[:3]
    if top:
        lines.append("")
        lines.append("<b>Главные флаги:</b>")
        for f in top:
            dot = "🔴" if f.severity == "red" else "🟡"
            lines.append(f"{dot} <b>{_shorten(f.name, 60)}</b> — {_shorten(f.message, 220)}")

    if assessment.recommendations:
        lines.append("")
        lines.append("<b>Что сделать сейчас:</b>")
        for rec in assessment.recommendations[:3]:
            lines.append(f"• {_shorten(rec, 220)}")
    return "\n".join(lines)


def _format_all_flags(assessment: RiskAssessment) -> list[str]:
    """Разбить полный список флагов на сообщения ≤4000 символов."""
    if not assessment.flags:
        return ["По выписке сработавших флагов нет. 🎉"]
    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0
    for f in sorted(assessment.flags, key=lambda x: x.contribution, reverse=True):
        dot = "🔴" if f.severity == "red" else "🟡"
        block = (
            f"{dot} <b>{f.name}</b> ({f.category})\n"
            f"<i>{_shorten(f.law, 120)}</i>\n"
            f"{_shorten(f.message, 350)}\n"
            f"💡 {_shorten(f.action_hint, 250)}\n"
        )
        if buf_len + len(block) > 3500 and buf:
            chunks.append("\n".join(buf))
            buf, buf_len = [], 0
        buf.append(block)
        buf_len += len(block)
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def _shorten(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ----------------------------- ядро анализа ----------------------------


def _thresholds_for(max_protect: bool) -> Thresholds:
    return DEFAULT_THRESHOLDS.tighten(0.25) if max_protect else DEFAULT_THRESHOLDS


async def _run_analysis(message: Message, file_bytes: bytes, filename: str, store: SessionStore) -> None:
    chat_id = message.chat.id
    sess = store.get(chat_id)
    thinking = await message.answer(T.PARSING)

    def _blocking() -> tuple:
        df, info = parse_statement(file_bytes, filename_hint=filename)
        feat = compute_features(df)
        thresholds = _thresholds_for(sess.max_protect)
        assess = assess_risk(feat, thresholds=thresholds)
        analysis_id = save_analysis(
            feat,
            assess,
            bank=info.bank,
            date_min=info.date_min.to_pydatetime() if info.date_min is not None else None,
            date_max=info.date_max.to_pydatetime() if info.date_max is not None else None,
            rows_parsed=info.rows_parsed,
            meta={"source": "telegram", "filename": filename},
        )
        return df, info, feat, assess, analysis_id

    try:
        df, info, feat, assess, analysis_id = await asyncio.to_thread(_blocking)
    except Exception as exc:  # noqa: BLE001 — показываем пользователю короткое сообщение
        logger.exception("analysis failed for chat %s", chat_id)
        await thinking.edit_text(T.ERROR_GENERIC.format(err=_shorten(str(exc), 200)))
        return

    sess.df = df
    sess.info = info
    sess.features = feat
    sess.assessment = assess
    sess.whatif_overrides = {}

    await thinking.edit_text(
        _format_assessment(
            assess, bank=info.bank, rows_parsed=info.rows_parsed, max_protect=sess.max_protect
        ),
        reply_markup=after_analysis(),
    )
    logger.info(
        "analysis saved id=%s chat=%s level=%s score=%.1f",
        analysis_id,
        chat_id,
        assess.level.value,
        assess.risk_score,
    )


# ----------------------------- хэндлеры --------------------------------


def build_dispatcher(store: SessionStore | None = None) -> Dispatcher:
    """Собрать :class:`Dispatcher` со всеми хэндлерами."""
    store = store or SessionStore()
    dp = Dispatcher()

    # ---- /start ----
    @dp.message(Command("start"))
    async def on_start(msg: Message) -> None:
        sess = store.get(msg.chat.id)
        await msg.answer(T.WELCOME, reply_markup=main_menu(sess.max_protect))

    @dp.message(Command("help"))
    async def on_help(msg: Message) -> None:
        await msg.answer(T.HELP, reply_markup=back_to_menu())

    @dp.message(Command("menu"))
    async def on_menu_cmd(msg: Message) -> None:
        sess = store.get(msg.chat.id)
        await msg.answer("Главное меню:", reply_markup=main_menu(sess.max_protect))

    # ---- callback: меню / навигация ----
    @dp.callback_query(F.data == "menu")
    async def cb_menu(cb: CallbackQuery) -> None:
        sess = store.get(cb.message.chat.id)
        await cb.message.edit_text("Главное меню:", reply_markup=main_menu(sess.max_protect))
        await cb.answer()

    @dp.callback_query(F.data == "help")
    async def cb_help(cb: CallbackQuery) -> None:
        await cb.message.edit_text(T.HELP, reply_markup=back_to_menu())
        await cb.answer()

    @dp.callback_query(F.data == "upload")
    async def cb_upload(cb: CallbackQuery) -> None:
        await cb.message.edit_text(T.UPLOAD_PROMPT, reply_markup=back_to_menu())
        await cb.answer()

    @dp.callback_query(F.data == "toggle_protect")
    async def cb_toggle_protect(cb: CallbackQuery) -> None:
        sess = store.get(cb.message.chat.id)
        sess.max_protect = not sess.max_protect
        body = T.MAX_PROTECT_ON if sess.max_protect else T.MAX_PROTECT_OFF
        await cb.message.edit_text(body, reply_markup=main_menu(sess.max_protect))
        await cb.answer()

    @dp.callback_query(F.data == "last")
    async def cb_last(cb: CallbackQuery) -> None:
        sess = store.get(cb.message.chat.id)
        if sess.assessment is None or sess.info is None:
            await cb.answer(T.NO_FILE_YET, show_alert=True)
            return
        await cb.message.edit_text(
            _format_assessment(
                sess.assessment,
                bank=sess.info.bank,
                rows_parsed=sess.info.rows_parsed,
                max_protect=sess.max_protect,
            ),
            reply_markup=after_analysis(),
        )
        await cb.answer()

    @dp.callback_query(F.data == "flags_all")
    async def cb_flags_all(cb: CallbackQuery) -> None:
        sess = store.get(cb.message.chat.id)
        if sess.assessment is None:
            await cb.answer(T.NO_FILE_YET, show_alert=True)
            return
        chunks = _format_all_flags(sess.assessment)
        for i, chunk in enumerate(chunks):
            kw = {"reply_markup": back_to_menu()} if i == len(chunks) - 1 else {}
            await cb.message.answer(chunk, **kw)
        await cb.answer()

    # ---- отчёты ----
    @dp.callback_query(F.data == "report_pdf")
    async def cb_report_pdf(cb: CallbackQuery) -> None:
        sess = store.get(cb.message.chat.id)
        if sess.assessment is None or sess.features is None or sess.info is None:
            await cb.answer(T.NO_FILE_YET, show_alert=True)
            return

        def _blocking() -> bytes:
            return build_pdf_report(
                sess.features,
                sess.assessment,
                bank=sess.info.bank,
                date_min=sess.info.date_min.to_pydatetime() if sess.info.date_min is not None else None,
                date_max=sess.info.date_max.to_pydatetime() if sess.info.date_max is not None else None,
            )

        pdf_bytes = await asyncio.to_thread(_blocking)
        fname = f"115riskguard_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        await cb.message.answer_document(
            BufferedInputFile(pdf_bytes, filename=fname),
            caption="📄 Полный PDF-отчёт с флагами, метриками и планом действий.",
        )
        await cb.answer()

    @dp.callback_query(F.data == "report_xlsx")
    async def cb_report_xlsx(cb: CallbackQuery) -> None:
        sess = store.get(cb.message.chat.id)
        if sess.assessment is None or sess.features is None or sess.df is None:
            await cb.answer(T.NO_FILE_YET, show_alert=True)
            return

        def _blocking() -> bytes:
            return build_excel_report(
                sess.df,
                sess.features,
                sess.assessment,
                bank=sess.info.bank if sess.info else "—",
            )

        xlsx_bytes = await asyncio.to_thread(_blocking)
        fname = f"115riskguard_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        await cb.message.answer_document(
            BufferedInputFile(xlsx_bytes, filename=fname),
            caption="📊 Excel с листами: Сводка / Флаги / План / Метрики.",
        )
        await cb.answer()

    # ---- what-if ----
    @dp.callback_query(F.data == "whatif")
    async def cb_whatif(cb: CallbackQuery) -> None:
        sess = store.get(cb.message.chat.id)
        if sess.features is None:
            await cb.answer(T.NO_FILE_YET, show_alert=True)
            return
        await cb.message.edit_text(T.WHAT_IF_PROMPT, reply_markup=whatif_menu())
        await cb.answer()

    @dp.callback_query(F.data.startswith("wi:"))
    async def cb_whatif_apply(cb: CallbackQuery) -> None:
        sess = store.get(cb.message.chat.id)
        if sess.features is None:
            await cb.answer(T.NO_FILE_YET, show_alert=True)
            return
        _, kind, *rest = cb.data.split(":")
        if kind == "reset":
            sess.whatif_overrides = {}
        else:
            value = float(rest[0])
            sess.whatif_overrides[kind] = sess.whatif_overrides.get(kind, 0.0) + value

        adjusted = whatif_adjust_features(
            sess.features,
            add_p2p_30d=int(sess.whatif_overrides.get("p2p", 0)),
            add_crypto_ops=int(sess.whatif_overrides.get("crypto", 0)),
            add_cash_share=sess.whatif_overrides.get("cash", 0.0),
            add_large_income=sess.whatif_overrides.get("income", 0.0),
        )
        new_assess = assess_risk(adjusted, thresholds=_thresholds_for(sess.max_protect))

        base_score = sess.assessment.risk_score if sess.assessment else 0.0
        delta = new_assess.risk_score - base_score
        sign = "▲" if delta > 0.5 else ("▼" if delta < -0.5 else "≈")
        summary = (
            "🧪 <b>Текущие наложения:</b>\n"
            + (
                "\n".join(
                    f"• +{v:g} {k}" for k, v in sess.whatif_overrides.items() if v
                )
                or "• пока ничего не добавлено"
            )
            + f"\n\nНовый балл: <b>{new_assess.risk_score:.0f}/100</b> "
            f"({sign} {abs(delta):.1f} от базового)\n"
            f"Уровень: {T.LEVEL_EMOJI.get(new_assess.level.value, '⚪️')} "
            f"{T.LEVEL_TEXT_RU.get(new_assess.level.value, '—')}"
        )
        await cb.message.edit_text(summary, reply_markup=whatif_menu())
        await cb.answer()

    # ---- история ----
    @dp.callback_query(F.data == "history")
    async def cb_history(cb: CallbackQuery) -> None:
        db = os.environ.get("RISKGUARD_DB", "data/history.db")
        items = await asyncio.to_thread(list_analyses, 10, db)
        if not items:
            await cb.message.edit_text(T.HISTORY_EMPTY, reply_markup=back_to_menu())
            await cb.answer()
            return
        await cb.message.edit_text(
            "📚 <b>Последние анализы</b>\nНажмите любой, чтобы посмотреть детали:",
            reply_markup=history_list(items),
        )
        await cb.answer()

    @dp.callback_query(F.data.startswith("hist:"))
    async def cb_hist_item(cb: CallbackQuery) -> None:
        analysis_id = int(cb.data.split(":", 1)[1])
        db = os.environ.get("RISKGUARD_DB", "data/history.db")
        rec = await asyncio.to_thread(load_analysis, analysis_id, db)
        if rec is None:
            await cb.answer("Запись не найдена.", show_alert=True)
            return
        level = (rec.get("level") or "green").lower()
        emoji = T.LEVEL_EMOJI.get(level, "⚪️")
        lines = [
            f"{emoji} <b>{T.LEVEL_TEXT_RU.get(level, '—')}</b> — "
            f"{float(rec.get('risk_score') or 0):.0f}/100",
            f"🏦 Банк: <b>{rec.get('bank') or '—'}</b>",
            f"📊 Операций: <b>{rec.get('rows_parsed') or 0}</b>",
            f"🔴/🟡: <b>{rec.get('red_flags') or 0}/{rec.get('yellow_flags') or 0}</b>",
            f"🕒 {(rec.get('created_at') or '')[:19].replace('T', ' ')}",
        ]
        flags = rec.get("flags") or []
        if flags:
            lines.append("")
            lines.append("<b>Флаги:</b>")
            for f in flags[:10]:
                dot = "🔴" if f.get("severity") == "red" else "🟡"
                lines.append(f"{dot} {_shorten(f.get('name', ''), 60)}")
        await cb.message.edit_text("\n".join(lines), reply_markup=back_to_menu())
        await cb.answer()

    # ---- загрузка файла ----
    @dp.message(F.document)
    async def on_document(msg: Message, bot: Bot) -> None:
        doc = msg.document
        if doc is None:
            return
        if doc.file_size and doc.file_size > _MAX_FILE_SIZE_BYTES:
            await msg.answer(
                f"Файл слишком большой ({doc.file_size / 1024 / 1024:.1f} МБ). "
                f"Лимит — 15 МБ."
            )
            return
        filename = doc.file_name or "statement.csv"
        lower = filename.lower()
        if not lower.endswith((".csv", ".xlsx", ".xls", ".pdf", ".tsv", ".txt")):
            await msg.answer(
                "Поддерживаются CSV, Excel (.xlsx/.xls) и PDF-выписки. "
                "Попробуйте сохранить выписку в одном из этих форматов."
            )
            return

        buf = io.BytesIO()
        await bot.download(doc, destination=buf)
        buf.seek(0)
        await _run_analysis(msg, buf.read(), filename, store)

    # нетипичные сообщения → главное меню
    @dp.message()
    async def on_any(msg: Message) -> None:
        sess = store.get(msg.chat.id)
        await msg.answer(
            "Я бот 115RiskGuard. Чтобы начать — нажмите кнопку ниже или отправьте /start.",
            reply_markup=main_menu(sess.max_protect),
        )

    return dp


async def run(token: str | None = None) -> None:
    """Асинхронный entry-point — запустить polling."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. Получите токен у @BotFather "
            "и экспортируйте переменную окружения TELEGRAM_BOT_TOKEN."
        )
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher()
    me = await bot.get_me()
    logger.info("Bot started as @%s", me.username)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


__all__ = ["build_dispatcher", "run", "_format_assessment", "_format_all_flags"]
