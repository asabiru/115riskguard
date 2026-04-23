"""Извлечение поведенческих признаков из нормализованной выписки.

Этот модуль превращает таблицу транзакций (см. :mod:`riskguard.parser`) в
:class:`StatementFeatures` — плоский dataclass с агрегатами, которые
дальше используются правилами :mod:`riskguard.risk_engine` и ML-моделью.

Дизайн-решения
--------------

* Признаки считаются на всей выписке сразу (без скользящих окон сверх
  необходимого), чтобы пайплайн был быстрым даже на больших выписках.
* Везде используются подписанные суммы: ``amount > 0`` — зачисление,
  ``amount < 0`` — списание.  Это соответствует канонической схеме
  парсера.
* Признаки устойчивы к пустой выписке: все поля корректно
  инициализируются нулями.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd

from .constants import (
    BUSINESS_KEYWORDS,
    CANON_AMOUNT,
    CANON_CHANNEL,
    CANON_COUNTERPARTY,
    CANON_DATE,
    CANON_DESCRIPTION,
    CRYPTO_KEYWORDS,
    GAMBLING_KEYWORDS,
    SALARY_KEYWORDS,
)

# ----------------------------- dataclass -------------------------------


@dataclass
class StatementFeatures:
    """Агрегированные признаки одной банковской выписки.

    Значения полей предназначены как для rule-based движка, так и для
    дообучения ML-модели.  Все суммы — в валюте выписки (обычно ₽).
    """

    # базовые агрегаты
    days_observed: int = 0
    tx_count: int = 0
    income_total: float = 0.0
    expense_total: float = 0.0
    net_flow: float = 0.0
    turnover_total: float = 0.0
    monthly_turnover: float = 0.0

    # P2P
    p2p_count: int = 0
    p2p_incoming_count: int = 0
    p2p_outgoing_count: int = 0
    p2p_unique_counterparties: int = 0
    p2p_max_per_day: int = 0
    p2p_last7d: int = 0
    p2p_last30d: int = 0

    # транзит
    same_day_turnover_share: float = 0.0
    residual_ratio: float = 1.0
    transit_days_count: int = 0

    # мелкие операции
    small_tx_count: int = 0
    small_tx_per_day_max: int = 0

    # крупные поступления
    large_income_count: int = 0
    largest_income: float = 0.0

    # наличные
    cash_volume: float = 0.0
    cash_ratio: float = 0.0

    # крипта / букмекеры
    crypto_ops_count: int = 0
    gambling_ops_count: int = 0

    # бизнес-паттерн
    incoming_unique_counterparties: int = 0
    incoming_from_individuals_count: int = 0
    business_like_score: float = 0.0

    # динамика
    turnover_spike_ratio: float = 1.0
    max_daily_turnover: float = 0.0

    # антифрод 161-ФЗ
    new_counterparty_share: float = 0.0
    night_tx_ratio: float = 0.0

    # зарплатный якорь — отсутствие регулярной зп = хуже
    has_salary_anchor: bool = False

    # детали для отчёта (не участвуют в ML-модели)
    evidence: dict[str, list[dict]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Вернуть plain-dict (для сохранения в SQLite / JSON)."""
        data = asdict(self)
        data.pop("evidence", None)
        return data


# ----------------------------- helpers ---------------------------------


def _is_p2p(channel: str) -> bool:
    return channel == "p2p"


def _extract_counterparty(desc: str, counterparty: str) -> str:
    """Собрать ключ-идентификатор контрагента для подсчёта уникальных."""
    cp = (counterparty or "").strip()
    if cp:
        return cp.lower()
    # используем имя из описания: берём первое разумное слово после ключевой фразы
    text = (desc or "").lower()
    return text[:64]


def _matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in text for kw in keywords)


# ----------------------------- основной расчёт -------------------------


def compute_features(df: pd.DataFrame, *, today: pd.Timestamp | None = None) -> StatementFeatures:
    """Посчитать :class:`StatementFeatures` по нормализованному DataFrame.

    Args:
        df: DataFrame с каноническими колонками (см. :mod:`parser`).
        today: отсчётная дата (например, дата последней операции).  Если
            ``None`` — берётся максимум ``date`` в выписке.  Нужно для
            корректного подсчёта «за последние N дней».
    """

    feat = StatementFeatures()
    if df.empty:
        return feat

    df = df.copy()
    df[CANON_DATE] = pd.to_datetime(df[CANON_DATE])
    df = df.sort_values(CANON_DATE)
    if today is None:
        today = df[CANON_DATE].max()

    date_min, date_max = df[CANON_DATE].min(), df[CANON_DATE].max()
    feat.days_observed = max(1, int((date_max - date_min).days) + 1)
    feat.tx_count = int(len(df))

    # базовые суммы
    income_mask = df[CANON_AMOUNT] > 0
    expense_mask = df[CANON_AMOUNT] < 0
    feat.income_total = float(df.loc[income_mask, CANON_AMOUNT].sum())
    feat.expense_total = float(-df.loc[expense_mask, CANON_AMOUNT].sum())
    feat.net_flow = feat.income_total - feat.expense_total
    feat.turnover_total = feat.income_total + feat.expense_total
    feat.monthly_turnover = feat.turnover_total * (30.0 / feat.days_observed)

    # P2P -------------------------------------------------------------
    p2p_mask = df[CANON_CHANNEL].eq("p2p")
    p2p_df = df.loc[p2p_mask]
    feat.p2p_count = int(len(p2p_df))
    feat.p2p_incoming_count = int((p2p_df[CANON_AMOUNT] > 0).sum())
    feat.p2p_outgoing_count = int((p2p_df[CANON_AMOUNT] < 0).sum())
    if not p2p_df.empty:
        cps = [
            _extract_counterparty(d, c)
            for d, c in zip(p2p_df[CANON_DESCRIPTION], p2p_df[CANON_COUNTERPARTY], strict=False)
        ]
        feat.p2p_unique_counterparties = int(len({c for c in cps if c}))
        per_day = p2p_df.groupby(p2p_df[CANON_DATE].dt.date).size()
        feat.p2p_max_per_day = int(per_day.max()) if not per_day.empty else 0
        d7 = today - timedelta(days=7)
        d30 = today - timedelta(days=30)
        feat.p2p_last7d = int((p2p_df[CANON_DATE] >= d7).sum())
        feat.p2p_last30d = int((p2p_df[CANON_DATE] >= d30).sum())

    # транзит ---------------------------------------------------------
    day_groups = df.groupby(df[CANON_DATE].dt.date)
    same_day_min_flow = []
    transit_days = 0
    for _, grp in day_groups:
        day_in = grp.loc[grp[CANON_AMOUNT] > 0, CANON_AMOUNT].sum()
        day_out = -grp.loc[grp[CANON_AMOUNT] < 0, CANON_AMOUNT].sum()
        if day_in > 0:
            share = min(day_in, day_out) / day_in
            same_day_min_flow.append(share)
            if share >= 0.8 and day_in >= 50_000:
                transit_days += 1
    feat.same_day_turnover_share = float(np.mean(same_day_min_flow)) if same_day_min_flow else 0.0
    feat.transit_days_count = int(transit_days)

    # residual ratio: (чистый остаток) / (входящие)  — чем меньше, тем хуже
    if feat.income_total > 0:
        feat.residual_ratio = max(0.0, feat.net_flow / feat.income_total)

    # мелкие операции -------------------------------------------------
    small_mask = (df[CANON_AMOUNT].abs() < 3_000) & p2p_mask & income_mask
    feat.small_tx_count = int(small_mask.sum())
    if feat.small_tx_count:
        per_day_small = df.loc[small_mask].groupby(df.loc[small_mask, CANON_DATE].dt.date).size()
        feat.small_tx_per_day_max = int(per_day_small.max()) if not per_day_small.empty else 0

    # крупные поступления -------------------------------------------
    large_mask = df[CANON_AMOUNT] >= 300_000
    feat.large_income_count = int(large_mask.sum())
    feat.largest_income = float(df.loc[income_mask, CANON_AMOUNT].max()) if income_mask.any() else 0.0

    # наличные -------------------------------------------------------
    cash_mask = df[CANON_CHANNEL].eq("cash")
    feat.cash_volume = float(df.loc[cash_mask, CANON_AMOUNT].abs().sum())
    if feat.turnover_total > 0:
        feat.cash_ratio = feat.cash_volume / feat.turnover_total

    # крипта / букмекеры --------------------------------------------
    descriptions = df[CANON_DESCRIPTION].astype(str).str.lower()
    feat.crypto_ops_count = int(descriptions.apply(lambda s: _matches_any(s, CRYPTO_KEYWORDS)).sum())
    feat.gambling_ops_count = int(descriptions.apply(lambda s: _matches_any(s, GAMBLING_KEYWORDS)).sum())

    # бизнес-паттерн ------------------------------------------------
    incoming = df.loc[income_mask]
    if not incoming.empty:
        cps = [
            _extract_counterparty(d, c)
            for d, c in zip(incoming[CANON_DESCRIPTION], incoming[CANON_COUNTERPARTY], strict=False)
        ]
        feat.incoming_unique_counterparties = int(len({c for c in cps if c}))
    business_like_mask = income_mask & descriptions.apply(lambda s: _matches_any(s, BUSINESS_KEYWORDS))
    feat.incoming_from_individuals_count = int(business_like_mask.sum())
    if feat.incoming_unique_counterparties:
        feat.business_like_score = feat.incoming_from_individuals_count / max(1, feat.p2p_incoming_count or 1)

    # динамика ------------------------------------------------------
    daily_turnover = df.groupby(df[CANON_DATE].dt.date)[CANON_AMOUNT].apply(lambda s: float(s.abs().sum()))
    feat.max_daily_turnover = float(daily_turnover.max()) if not daily_turnover.empty else 0.0
    if len(daily_turnover) >= 3:
        median = float(daily_turnover.median()) or 1.0
        feat.turnover_spike_ratio = feat.max_daily_turnover / median

    # антифрод -------------------------------------------------------
    if len(df) >= 2:
        seen: set[str] = set()
        new_count = 0
        for d, c in zip(df[CANON_DESCRIPTION], df[CANON_COUNTERPARTY], strict=False):
            key = _extract_counterparty(d, c)
            if key and key not in seen:
                seen.add(key)
                new_count += 1
        feat.new_counterparty_share = new_count / max(1, feat.tx_count)
    night_mask = df[CANON_DATE].dt.hour.between(0, 5, inclusive="both")
    feat.night_tx_ratio = float(night_mask.mean())

    feat.has_salary_anchor = bool(descriptions.apply(lambda s: _matches_any(s, SALARY_KEYWORDS)).any())

    # evidence для отчёта -------------------------------------------
    feat.evidence = _build_evidence(df)
    return feat


# ----------------------------- evidence ----------------------------


def _build_evidence(df: pd.DataFrame) -> dict[str, list[dict]]:
    """Набрать примеры операций для каждой категории (для пояснений в отчёте)."""
    ev: dict[str, list[dict]] = {}

    def _sample(mask: pd.Series, n: int = 5) -> list[dict]:
        sub = df.loc[mask].sort_values(CANON_AMOUNT, key=lambda s: s.abs(), ascending=False).head(n)
        return [
            {
                "date": row[CANON_DATE].strftime("%Y-%m-%d"),
                "amount": float(row[CANON_AMOUNT]),
                "description": str(row[CANON_DESCRIPTION])[:140],
                "channel": str(row[CANON_CHANNEL]),
            }
            for _, row in sub.iterrows()
        ]

    descriptions = df[CANON_DESCRIPTION].astype(str).str.lower()
    ev["p2p_samples"] = _sample(df[CANON_CHANNEL].eq("p2p"))
    ev["crypto_samples"] = _sample(descriptions.apply(lambda s: _matches_any(s, CRYPTO_KEYWORDS)))
    ev["cash_samples"] = _sample(df[CANON_CHANNEL].eq("cash"))
    ev["large_income_samples"] = _sample(df[CANON_AMOUNT] >= 300_000)
    ev["business_samples"] = _sample(descriptions.apply(lambda s: _matches_any(s, BUSINESS_KEYWORDS)))
    return ev
