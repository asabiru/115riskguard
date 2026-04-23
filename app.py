"""Streamlit-приложение 115RiskGuard.

Запуск:
    streamlit run app.py

Поток работы:
    1. Пользователь выбирает банк (или «авто») и загружает выписку
       (CSV/XLSX/PDF). Все данные остаются на машине пользователя.
    2. Модули :mod:`riskguard.parser` и :mod:`riskguard.feature_engineering`
       считают признаки; :mod:`riskguard.risk_engine` — итоговую оценку.
    3. Дашборд показывает сводку, флаги, графики, рекомендации.
    4. Пользователь может скачать PDF/Excel-отчёт, сохранить анализ в
       локальной истории и поиграть с what-if-симулятором.
"""

from __future__ import annotations

import dataclasses
import io
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from riskguard.constants import (
    CANON_AMOUNT,
    CANON_CATEGORY,
    CANON_CHANNEL,
    CANON_COUNTERPARTY,
    CANON_DATE,
    CANON_DESCRIPTION,
    DEFAULT_THRESHOLDS,
    LEVEL_COLORS,
    RiskLevel,
    Thresholds,
)
from riskguard.feature_engineering import StatementFeatures, compute_features
from riskguard.parser import ParseInfo, parse_statement
from riskguard.report_generator import build_excel_report, build_pdf_report
from riskguard.risk_engine import RiskAssessment, assess_risk, whatif_adjust_features
from riskguard.storage import (
    DEFAULT_DB_PATH,
    delete_analysis,
    list_analyses,
    load_analysis,
    save_analysis,
)

# --------------------------- streamlit setup ---------------------------

st.set_page_config(
    page_title="115RiskGuard — риск-контроль 115-ФЗ",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)

_ST_STYLE = """
<style>
    .stApp { background: #f7f8fb; }
    .metric-card { background:#fff; border-radius:14px; padding:1.1rem 1.4rem;
                   border:1px solid #e7e9ee; box-shadow:0 1px 2px rgba(15,23,42,.04); }
    .flag-card { background:#fff; border-radius:12px; padding:1rem 1.2rem;
                 border:1px solid #e7e9ee; margin-bottom:.75rem; }
    .flag-red   { border-left:5px solid #d1242f; }
    .flag-yellow { border-left:5px solid #f2a93b; }
    .flag-title { font-weight:600; font-size:1.05rem; color:#1f2a44; margin-bottom:.25rem;}
    .muted { color:#596478; font-size:.9rem; }
</style>
"""
st.markdown(_ST_STYLE, unsafe_allow_html=True)


# --------------------------- state -------------------------------------


def _init_state() -> None:
    defaults = {
        "transactions": None,
        "parse_info": None,
        "features": None,
        "assessment": None,
        "bank_hint": None,
        "analysis_id": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


_init_state()


# --------------------------- helpers -----------------------------------


def _render_header() -> None:
    st.markdown(
        """
        # 🛡 115RiskGuard
        **Индивидуальный риск-контроль по 115-ФЗ.** Загрузите выписку — мы не пугаем,
        а показываем конкретные паттерны, из-за которых банки блокировали счета в 2025–2026,
        и даём персональный план, что поправить прямо сейчас.
        Всё считается локально, файл не уходит с вашей машины.
        """
    )


def _sidebar() -> tuple[Thresholds, bool, bool]:
    st.sidebar.header("⚙ Настройки анализа")
    bank_choice = st.sidebar.selectbox(
        "Банк выписки",
        ["Автоопределение", "Сбер", "Тинькофф", "Альфа-Банк", "ВТБ", "Газпромбанк", "Универсальный"],
        help="Можно оставить автоопределение — парсер сам попробует узнать формат.",
    )
    if bank_choice == "Автоопределение":
        st.session_state["bank_hint"] = None
    else:
        st.session_state["bank_hint"] = bank_choice

    max_defense = st.sidebar.toggle(
        "Режим максимальной защиты",
        value=False,
        help="Применяет более строгие пороги и подсвечивает даже пограничные паттерны.",
    )
    save_to_history = st.sidebar.toggle(
        "Сохранять анализ в локальной истории",
        value=True,
        help=f"История хранится в SQLite по пути {DEFAULT_DB_PATH}.",
    )
    with st.sidebar.expander("Дополнительно: тонкая настройка порогов"):
        thresholds = _threshold_controls(max_defense)

    st.sidebar.caption(
        "Мы следуем МР ЦБ 4/16/17/18/19-МР, положениям 375-П и 519-П, "
        "а также реальным кейсам banki.ru."
    )
    return thresholds, max_defense, save_to_history


def _threshold_controls(max_defense: bool) -> Thresholds:
    """Возвращает настроенный Thresholds (с учётом режима защиты)."""
    base = DEFAULT_THRESHOLDS.tighten() if max_defense else DEFAULT_THRESHOLDS
    return dataclasses.replace(
        base,
        p2p_per_day_red=int(st.slider("P2P/день — красная зона", 5, 50, base.p2p_per_day_red)),
        p2p_30d_red=int(st.slider("P2P/30 дней — красная зона", 20, 200, base.p2p_30d_red)),
        large_income_rub_red=float(
            st.slider("Крупное поступление (₽) — красная зона", 100_000, 2_000_000, int(base.large_income_rub_red))
        ),
        cash_ratio_red=float(st.slider("Доля наличных — красная зона", 0.1, 0.9, base.cash_ratio_red, 0.05)),
    )


def _render_level_badge(level_label: str, level_color: str, score: float) -> None:
    st.markdown(
        f"""
        <div class="metric-card" style="border-left:6px solid {level_color};">
          <div style="font-size:.85rem;color:#596478;text-transform:uppercase;letter-spacing:.04em;">Итоговый уровень</div>
          <div style="font-size:1.6rem;font-weight:600;color:{level_color};margin-top:.3rem">{level_label}</div>
          <div style="margin-top:.4rem">Балл риска: <b>{score:.0f} / 100</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_metric(title: str, value: str, help_text: str = "") -> None:
    help_html = f'<div class="muted">{help_text}</div>' if help_text else ""
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="muted" style="text-transform:uppercase;font-size:.8rem;letter-spacing:.05em">{title}</div>
          <div style="font-size:1.4rem;font-weight:600;color:#1f2a44;margin-top:.2rem">{value}</div>
          {help_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_flag(flag) -> None:
    klass = "flag-red" if flag.severity == "red" else "flag-yellow"
    severity_label = "Красный" if flag.severity == "red" else "Жёлтый"
    case_html = f'<div class="muted">Источник: {flag.case_reference}</div>' if flag.case_reference else ""
    st.markdown(
        f"""
        <div class="flag-card {klass}">
          <div class="flag-title">● {flag.name} <span class="muted">· {severity_label} · вклад {flag.contribution:.1f}</span></div>
          <div>{flag.message}</div>
          <div style="margin-top:.5rem"><b>Почему это опасно:</b> {flag.why_dangerous}</div>
          <div style="margin-top:.3rem"><b>Как снизить риск:</b> {flag.action_hint}</div>
          <div class="muted" style="margin-top:.35rem">Нормативная база: {flag.law}</div>
          {case_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_charts(df: pd.DataFrame, features: StatementFeatures) -> None:
    if df.empty:
        st.info("Нет операций для графиков.")
        return
    daily = (
        df.assign(abs_amount=lambda d: d[CANON_AMOUNT].abs())
        .groupby([df[CANON_DATE].dt.date.rename("day"), CANON_CHANNEL])["abs_amount"]
        .sum()
        .reset_index()
    )
    daily["day"] = pd.to_datetime(daily["day"])

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(
            daily,
            x="day",
            y="abs_amount",
            color=CANON_CHANNEL,
            title="Оборот по дням (разрезом по каналам)",
            labels={"abs_amount": "Объём, ₽", "day": "Дата", CANON_CHANNEL: "Канал"},
        )
        fig.update_layout(height=320, margin=dict(t=40, l=10, r=10, b=10), legend_title_text="")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        channel_mix = df.groupby(CANON_CHANNEL)[CANON_AMOUNT].apply(lambda s: float(s.abs().sum())).reset_index()
        fig = px.pie(
            channel_mix,
            names=CANON_CHANNEL,
            values=CANON_AMOUNT,
            title="Структура оборота по каналам",
            hole=0.45,
        )
        fig.update_layout(height=320, margin=dict(t=40, l=10, r=10, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # динамика P2P
    p2p = df[df[CANON_CHANNEL].eq("p2p")].copy()
    if not p2p.empty:
        p2p_daily = p2p.groupby(p2p[CANON_DATE].dt.date).size().reset_index(name="p2p_count")
        p2p_daily[CANON_DATE] = pd.to_datetime(p2p_daily[CANON_DATE])
        fig = go.Figure()
        fig.add_trace(go.Bar(x=p2p_daily[CANON_DATE], y=p2p_daily["p2p_count"], name="P2P за день"))
        fig.add_hline(y=20, line_color=LEVEL_COLORS[RiskLevel.RED], line_dash="dash", annotation_text="красный порог")
        fig.add_hline(y=10, line_color=LEVEL_COLORS[RiskLevel.YELLOW], line_dash="dot", annotation_text="жёлтый порог")
        fig.update_layout(
            title="Число P2P-переводов по дням",
            height=320,
            margin=dict(t=40, l=10, r=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)


# --------------------------- processing --------------------------------


def _process_upload(upload) -> tuple[pd.DataFrame, ParseInfo] | None:
    data = upload.read()
    try:
        df, info = parse_statement(io.BytesIO(data), filename_hint=upload.name, bank_hint=st.session_state["bank_hint"])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось разобрать выписку: {exc}")
        return None
    if df.empty:
        st.error("Выписка пуста или не распознана — проверьте формат файла.")
        return None
    return df, info


def _run_assessment(df: pd.DataFrame, thresholds: Thresholds) -> tuple[StatementFeatures, RiskAssessment]:
    features = compute_features(df)
    assessment = assess_risk(features, thresholds=thresholds)
    return features, assessment


# --------------------------- pages -------------------------------------


def _page_analyze(thresholds: Thresholds, save_history: bool) -> None:
    uploaded = st.file_uploader(
        "Загрузите выписку физлица (CSV / XLSX / PDF)",
        type=["csv", "tsv", "xlsx", "xls", "pdf"],
        help="Поддержка Сбера, Тинькофф, Альфа-Банка, ВТБ, Газпромбанка и произвольных таблиц.",
    )
    if uploaded is not None:
        parsed = _process_upload(uploaded)
        if parsed is not None:
            df, info = parsed
            st.session_state["transactions"] = df
            st.session_state["parse_info"] = info
            features, assessment = _run_assessment(df, thresholds)
            st.session_state["features"] = features
            st.session_state["assessment"] = assessment
            if save_history:
                aid = save_analysis(
                    features,
                    assessment,
                    bank=info.bank,
                    date_min=info.date_min.to_pydatetime() if info.date_min is not None else None,
                    date_max=info.date_max.to_pydatetime() if info.date_max is not None else None,
                    rows_parsed=info.rows_parsed,
                    meta={"filename": uploaded.name},
                )
                st.session_state["analysis_id"] = aid
            for w in info.warnings:
                st.warning(w)

    features: StatementFeatures | None = st.session_state.get("features")
    assessment: RiskAssessment | None = st.session_state.get("assessment")
    info: ParseInfo | None = st.session_state.get("parse_info")
    df: pd.DataFrame | None = st.session_state.get("transactions")

    if features is None or assessment is None or info is None or df is None:
        st.info(
            "Пример поддерживаемых форматов лежит в папке `sample_data/` (Сбер, Тинькофф, "
            "Альфа, ВТБ, Газпромбанк). Можно загрузить любой из них, чтобы увидеть отчёт."
        )
        return

    _render_dashboard(df, info, features, assessment, thresholds)


def _render_dashboard(
    df: pd.DataFrame,
    info: ParseInfo,
    features: StatementFeatures,
    assessment: RiskAssessment,
    thresholds: Thresholds,
) -> None:
    st.subheader("Сводка")
    _render_level_badge(assessment.level_label, assessment.level_color, assessment.risk_score)
    cols = st.columns(4)
    with cols[0]:
        _render_metric("Вероятность блокировки", f"{assessment.probability * 100:.1f}%")
    with cols[1]:
        _render_metric("Период выписки", f"{info.date_range_days} дн.", help_text=f"Банк: {info.bank}")
    with cols[2]:
        _render_metric("Операций", f"{features.tx_count}")
    with cols[3]:
        red = sum(1 for f in assessment.flags if f.severity == "red")
        yellow = sum(1 for f in assessment.flags if f.severity == "yellow")
        _render_metric("Флагов", f"🔴 {red} · 🟡 {yellow}")

    st.markdown(f"> {assessment.summary}")

    tab_flags, tab_plan, tab_charts, tab_tx, tab_whatif, tab_export = st.tabs(
        ["Флаги", "План действий", "Графики", "Операции", "What-if", "Экспорт"]
    )
    with tab_flags:
        if not assessment.flags:
            st.success("Не нашли явных красных признаков — продолжайте так же.")
        else:
            for f in assessment.flags:
                _render_flag(f)
                if f.evidence:
                    with st.expander("Показать примеры операций, которые дали этот флаг"):
                        ev_df = pd.DataFrame(f.evidence)
                        st.dataframe(ev_df, use_container_width=True, hide_index=True)

    with tab_plan:
        st.markdown("#### Персональный план — что делать прямо сейчас")
        for i, rec in enumerate(assessment.recommendations, start=1):
            st.markdown(f"**{i}.** {rec}")

    with tab_charts:
        _render_charts(df, features)

    with tab_tx:
        st.dataframe(
            df[[CANON_DATE, CANON_AMOUNT, CANON_CHANNEL, CANON_CATEGORY, CANON_DESCRIPTION, CANON_COUNTERPARTY]],
            use_container_width=True,
            hide_index=True,
        )

    with tab_whatif:
        _render_whatif(features, thresholds)

    with tab_export:
        _render_exports(df, features, assessment, info)


def _render_whatif(base_features: StatementFeatures, thresholds: Thresholds) -> None:
    st.markdown(
        "Попробуйте смоделировать будущие операции: как изменится риск, если вы совершите ещё "
        "N P2P-переводов, получите крупную сумму или увеличите долю наличных."
    )
    c1, c2 = st.columns(2)
    with c1:
        add_p2p = st.slider("Добавить P2P-переводов за 30 дней", 0, 100, 0)
        add_big = st.number_input("Добавить крупное поступление, ₽", min_value=0, max_value=5_000_000, value=0, step=50_000)
    with c2:
        add_cash = st.slider("Увеличить долю наличных, %", 0, 50, 0)
        add_crypto = st.slider("Добавить операций с крипто-обменами", 0, 30, 0)
    sim_features = whatif_adjust_features(
        base_features,
        add_p2p_30d=add_p2p,
        add_large_income=float(add_big),
        add_cash_share=add_cash / 100,
        add_crypto_ops=add_crypto,
    )
    sim_assessment = assess_risk(sim_features, thresholds=thresholds)
    c3, c4 = st.columns(2)
    with c3:
        _render_metric("Исходный балл", f"{assess_risk(base_features, thresholds=thresholds).risk_score:.0f}")
    with c4:
        _render_metric(
            "Прогноз после изменений",
            f"{sim_assessment.risk_score:.0f}",
            help_text=sim_assessment.level_label,
        )
    st.markdown(f"> {sim_assessment.summary}")


def _render_exports(df: pd.DataFrame, features: StatementFeatures, assessment: RiskAssessment, info: ParseInfo) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    pdf_bytes = build_pdf_report(
        features,
        assessment,
        bank=info.bank,
        date_min=info.date_min.to_pydatetime() if info.date_min is not None else None,
        date_max=info.date_max.to_pydatetime() if info.date_max is not None else None,
    )
    xlsx_bytes = build_excel_report(df, features, assessment, bank=info.bank)
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "📄 Скачать PDF-отчёт",
            data=pdf_bytes,
            file_name=f"115riskguard_{ts}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
    with c2:
        st.download_button(
            "📊 Скачать Excel-отчёт",
            data=xlsx_bytes,
            file_name=f"115riskguard_{ts}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


def _page_history() -> None:
    st.subheader("История анализов")
    rows = list_analyses(limit=100)
    if not rows:
        st.info("Пока пусто — проанализируйте первую выписку на вкладке «Анализ».")
        return
    df = pd.DataFrame(rows)
    df["created_at"] = pd.to_datetime(df["created_at"])
    df = df.rename(
        columns={
            "id": "ID",
            "created_at": "Когда",
            "bank": "Банк",
            "date_min": "С",
            "date_max": "По",
            "rows_parsed": "Операций",
            "risk_score": "Балл",
            "probability": "Вероятность",
            "level": "Уровень",
            "red_flags": "🔴",
            "yellow_flags": "🟡",
        }
    )
    st.dataframe(df, use_container_width=True, hide_index=True)
    col1, col2 = st.columns(2)
    with col1:
        sel = st.number_input("ID записи для просмотра", min_value=0, value=int(df["ID"].max()))
        if st.button("Показать подробности"):
            record = load_analysis(int(sel))
            if record is None:
                st.error("Не найдено.")
            else:
                st.json(record)
    with col2:
        del_id = st.number_input("ID записи для удаления", min_value=0, value=0, key="del_id")
        if st.button("Удалить запись", type="secondary"):
            if delete_analysis(int(del_id)):
                st.success("Удалено. Обновите страницу.")
            else:
                st.warning("Запись не найдена.")


def _page_monitor(thresholds: Thresholds, save_history: bool) -> None:
    st.subheader("Еженедельный мониторинг — серия выписок")
    st.markdown(
        "Загрузите несколько выписок подряд (например, по одному файлу в неделю) — "
        "мы посчитаем тренд балла риска."
    )
    uploads = st.file_uploader(
        "Несколько выписок",
        type=["csv", "tsv", "xlsx", "xls", "pdf"],
        accept_multiple_files=True,
    )
    if not uploads:
        return
    points = []
    for up in uploads:
        parsed = _process_upload(up)
        if parsed is None:
            continue
        df, info = parsed
        features, assessment = _run_assessment(df, thresholds)
        if save_history:
            save_analysis(
                features,
                assessment,
                bank=info.bank,
                date_min=info.date_min.to_pydatetime() if info.date_min is not None else None,
                date_max=info.date_max.to_pydatetime() if info.date_max is not None else None,
                rows_parsed=info.rows_parsed,
                meta={"filename": up.name, "mode": "monitor"},
            )
        points.append(
            {
                "файл": up.name,
                "банк": info.bank,
                "период": f"{info.date_min} — {info.date_max}",
                "балл": round(assessment.risk_score, 1),
                "уровень": assessment.level_label,
                "🔴": sum(1 for f in assessment.flags if f.severity == "red"),
                "🟡": sum(1 for f in assessment.flags if f.severity == "yellow"),
            }
        )
    if points:
        df_points = pd.DataFrame(points)
        st.dataframe(df_points, use_container_width=True, hide_index=True)
        fig = px.line(df_points, x="файл", y="балл", markers=True, title="Динамика балла риска")
        fig.update_layout(height=320)
        st.plotly_chart(fig, use_container_width=True)


def _page_about() -> None:
    st.subheader("О проекте")
    st.markdown(
        """
        **115RiskGuard** — локальный инструмент для физлиц, который по вашей
        банковской выписке оценивает вероятность блокировки/приостановки счёта
        по 115-ФЗ *до* того, как это увидит антифрод банка.

        **Как это работает.** Rule-based движок собирает паттерны из
        методических рекомендаций ЦБ (МР 4/16/17/18/19-МР), положений 375-П и
        519-П, 161-ФЗ и реальных кейсов с banki.ru. Опционально — поверх
        можно подключить CatBoost-модель (см. `riskguard.ml_model`).

        **Приватность.** Файл выписки остаётся на вашем компьютере. История
        анализов лежит в локальной SQLite. Ничего никуда не отправляется.

        **Дисклеймер.** Мы не юристы и не ЦБ. Итоговое решение о блокировке
        принимает банк по своим внутренним моделям. Мы просто подсвечиваем
        паттерны, из-за которых блокировки массово случались в 2025–2026 —
        и даём конкретные шаги, что с этим делать.
        """
    )


# --------------------------- entrypoint ---------------------------------


def main() -> None:
    _render_header()
    thresholds, _max_defense, save_history = _sidebar()
    tab1, tab2, tab3, tab4 = st.tabs(["Анализ", "Мониторинг", "История", "О проекте"])
    with tab1:
        _page_analyze(thresholds, save_history)
    with tab2:
        _page_monitor(thresholds, save_history)
    with tab3:
        _page_history()
    with tab4:
        _page_about()


if __name__ == "__main__":
    main()
