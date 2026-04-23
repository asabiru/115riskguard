"""Генерация отчётов в PDF и Excel.

PDF делается через :mod:`reportlab` (надёжнее и легче подключать
кириллические шрифты, чем fpdf2).  Excel — через :mod:`xlsxwriter`:
несколько листов с операциями, агрегатами и планом действий.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .feature_engineering import StatementFeatures
from .risk_engine import RiskAssessment

logger = logging.getLogger(__name__)


# ------------------------ подключение кириллических шрифтов ---------------

_FONT_NAME = "RG-Body"
_FONT_BOLD = "RG-Body-Bold"
_FONTS_REGISTERED = False


def _register_fonts() -> tuple[str, str]:
    """Зарегистрировать шрифты с поддержкой кириллицы.

    Ищем в нескольких стандартных путях (Ubuntu + контейнер).  Если ни
    один не найден — откатываемся на встроенный ``Helvetica``, который
    поддерживает кириллицу через WinAnsi (качество ниже, но работает).
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return _FONT_NAME, _FONT_BOLD
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
        ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ]
    for reg, bold in candidates:
        if Path(reg).exists() and Path(bold).exists():
            pdfmetrics.registerFont(TTFont(_FONT_NAME, reg))
            pdfmetrics.registerFont(TTFont(_FONT_BOLD, bold))
            _FONTS_REGISTERED = True
            return _FONT_NAME, _FONT_BOLD
    logger.warning("TTF c кириллицей не найден, использую Helvetica (может испортить диакритику).")
    return "Helvetica", "Helvetica-Bold"


# ------------------------ PDF-отчёт ------------------------


def _styles(font: str, font_bold: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title",
            parent=base["Title"],
            fontName=font_bold,
            fontSize=22,
            leading=26,
            textColor=colors.HexColor("#1f2a44"),
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=font_bold,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor("#1f2a44"),
            spaceBefore=14,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=font,
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor("#1a1f36"),
        ),
        "small": ParagraphStyle(
            "small",
            parent=base["BodyText"],
            fontName=font,
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#596478"),
        ),
        "lead": ParagraphStyle(
            "lead",
            parent=base["BodyText"],
            fontName=font,
            fontSize=11.5,
            leading=15,
            textColor=colors.HexColor("#1a1f36"),
        ),
    }


def build_pdf_report(
    features: StatementFeatures,
    assessment: RiskAssessment,
    *,
    bank: str = "—",
    date_min: datetime | None = None,
    date_max: datetime | None = None,
) -> bytes:
    """Собрать PDF-отчёт и вернуть байты.  Не пишет на диск."""
    font, font_bold = _register_fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="Отчёт 115RiskGuard",
        author="115RiskGuard",
    )
    S = _styles(font, font_bold)
    story: list = []

    story.append(Paragraph("115RiskGuard · Отчёт по риску 115-ФЗ", S["title"]))
    period = "—"
    if date_min and date_max:
        period = f"{date_min.strftime('%d.%m.%Y')} — {date_max.strftime('%d.%m.%Y')}"
    header_rows = [
        ["Банк", bank],
        ["Период", period],
        ["Операций разобрано", f"{features.tx_count}"],
        ["Итоговый балл", f"{assessment.risk_score:.0f} / 100"],
        ["Вероятность блокировки", f"{assessment.probability * 100:.1f}%"],
        ["Уровень", assessment.level_label],
        ["Сгенерирован", datetime.now().strftime("%d.%m.%Y %H:%M")],
    ]
    header_table = Table(header_rows, colWidths=[5.5 * cm, 10.5 * cm])
    header_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTNAME", (0, 0), (0, -1), font_bold),
                ("FONTSIZE", (0, 0), (-1, -1), 10.5),
                ("TEXTCOLOR", (1, 5), (1, 5), colors.HexColor(assessment.level_color)),
                ("FONTNAME", (1, 5), (1, 5), font_bold),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e7e9ee")),
            ]
        )
    )
    story.append(header_table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(assessment.summary, S["lead"]))

    story.append(Paragraph("Что сработало и почему это опасно", S["h2"]))
    if not assessment.flags:
        story.append(Paragraph("Явных красных признаков нет — продолжайте в том же духе.", S["body"]))
    else:
        for flag in assessment.flags:
            color = colors.HexColor(flag.color)
            story.append(
                Paragraph(
                    f'<font color="{color.hexval()}"><b>● {flag.name}</b></font>  '
                    f'<font color="#596478">· вклад {flag.contribution:.1f}</font>',
                    S["body"],
                )
            )
            story.append(Paragraph(flag.message, S["body"]))
            story.append(Paragraph(f"<b>Почему это опасно:</b> {flag.why_dangerous}", S["body"]))
            story.append(
                Paragraph(
                    f"<b>Как снизить риск:</b> {flag.action_hint}",
                    S["body"],
                )
            )
            if flag.case_reference:
                story.append(Paragraph(f"Источник: {flag.case_reference}", S["small"]))
            story.append(Spacer(1, 0.25 * cm))

    story.append(Paragraph("Ваш персональный план действий", S["h2"]))
    for i, rec in enumerate(assessment.recommendations[:10], start=1):
        story.append(Paragraph(f"{i}. {rec}", S["body"]))

    story.append(Paragraph("Ключевые цифры выписки", S["h2"]))
    metrics = [
        ["Поступления", f"{features.income_total:,.0f} ₽"],
        ["Списания", f"{features.expense_total:,.0f} ₽"],
        ["Оборот за 30 дней", f"{features.monthly_turnover:,.0f} ₽"],
        ["P2P за 30 дней", str(features.p2p_last30d)],
        ["P2P макс/день", str(features.p2p_max_per_day)],
        ["Уникальных P2P-контрагентов", str(features.p2p_unique_counterparties)],
        ["Доля наличных", f"{features.cash_ratio * 100:.0f}%"],
        ["Остаточная доля (residual)", f"{features.residual_ratio * 100:.1f}%"],
        ["Операции с крипто-обменами", str(features.crypto_ops_count)],
        ["Всплеск оборота (× к медиане)", f"{features.turnover_spike_ratio:.1f}x"],
    ]
    metrics_table = Table(
        [[Paragraph(k.replace(",", " "), S["body"]), Paragraph(v.replace(",", " "), S["body"])] for k, v in metrics],
        colWidths=[9 * cm, 7 * cm],
    )
    metrics_table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e7e9ee")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(metrics_table)

    story.append(Spacer(1, 0.4 * cm))
    disclaimer = (
        "<b>Дисклеймер.</b> Отчёт не является юридической консультацией. Итоговое "
        "решение о блокировке принимает банк по своим внутренним моделям и с учётом "
        "ПОД/ФТ-практики. 115RiskGuard оценивает риск по публичным признакам "
        "ЦБ РФ и реальным кейсам 2025–2026 на banki.ru."
    )
    story.append(Paragraph(disclaimer, S["small"]))
    doc.build(story)
    return buf.getvalue()


# ------------------------ Excel ------------------------


def build_excel_report(
    df: pd.DataFrame,
    features: StatementFeatures,
    assessment: RiskAssessment,
    *,
    bank: str = "—",
) -> bytes:
    """Собрать Excel-отчёт (несколько листов) и вернуть байты."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        # --- Лист «Сводка» ---
        summary = pd.DataFrame(
            {
                "Параметр": [
                    "Банк",
                    "Операций разобрано",
                    "Итоговый балл",
                    "Вероятность блокировки",
                    "Уровень риска",
                    "Красных флагов",
                    "Жёлтых флагов",
                ],
                "Значение": [
                    bank,
                    features.tx_count,
                    f"{assessment.risk_score:.0f} / 100",
                    f"{assessment.probability * 100:.1f}%",
                    assessment.level_label,
                    sum(1 for f in assessment.flags if f.severity == "red"),
                    sum(1 for f in assessment.flags if f.severity == "yellow"),
                ],
            }
        )
        summary.to_excel(writer, index=False, sheet_name="Сводка")

        # --- Лист «Флаги» ---
        if assessment.flags:
            flags_df = pd.DataFrame(
                [
                    {
                        "Категория": f.category,
                        "Название": f.name,
                        "Серьёзность": "Красный" if f.severity == "red" else "Жёлтый",
                        "Вклад в балл": round(f.contribution, 2),
                        "Метрика": f.metric_value,
                        "Порог": f.metric_threshold,
                        "Нормативная база": f.law,
                        "Сообщение": f.message,
                        "Почему опасно": f.why_dangerous,
                        "Как снизить риск": f.action_hint,
                        "Источник": f.case_reference,
                    }
                    for f in assessment.flags
                ]
            )
        else:
            flags_df = pd.DataFrame([{"Нет сработавших флагов": ""}])
        flags_df.to_excel(writer, index=False, sheet_name="Флаги")

        # --- Лист «Признаки» ---
        feats = pd.DataFrame(list(features.to_dict().items()), columns=["Признак", "Значение"])
        feats.to_excel(writer, index=False, sheet_name="Признаки")

        # --- Лист «План действий» ---
        recs = pd.DataFrame(
            [{"#": i + 1, "Что делать": r} for i, r in enumerate(assessment.recommendations)]
        )
        recs.to_excel(writer, index=False, sheet_name="План_действий")

        # --- Лист «Операции» ---
        safe_tx = df.copy()
        for col in safe_tx.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]):
            safe_tx[col] = safe_tx[col].dt.tz_localize(None) if hasattr(safe_tx[col].dt, "tz_localize") else safe_tx[col]
        safe_tx.to_excel(writer, index=False, sheet_name="Операции")

        # базовое форматирование
        workbook = writer.book
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#1f2a44", "font_color": "#ffffff", "border": 1})
        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            ws.set_column(0, 30, 24)
            ws.set_row(0, 22, header_fmt)
    return buf.getvalue()
