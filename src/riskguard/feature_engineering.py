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
    CASH_DEPOSIT_KEYWORDS,
    CRYPTO_KEYWORDS,
    EXTERNAL_BANK_HINTS,
    GAMBLING_KEYWORDS,
    LIFESTYLE_KEYWORDS,
    SALARY_KEYWORDS,
    SELF_EMPLOYED_KEYWORDS,
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

    # --------- признаки из разбора banki.ru-кейсов 2025–2026 ---------
    # Мгновенный вывод (МР 16-МР п.4)
    fast_inout_share: float = 0.0
    fast_inout_pairs_count: int = 0

    # Жизнеобеспечение (МР 16-МР п.8)
    has_lifestyle_payments: bool = False
    lifestyle_payments_count: int = 0
    days_without_lifestyle: int = 0

    # Круглосуточная активность (МР 16-МР п.5)
    active_hours_span: int = 0
    active_hours_avg_per_day: float = 0.0

    # СБП-вывод сразу после зачисления (кейсы Сбер/Т-Банк)
    sbp_out_after_income_share: float = 0.0

    # Третьи лица вносят наличные (МР 11-МР 2025)
    third_party_cash_deposits_count: int = 0

    # Переводы ИП/самозанятым
    ip_samozanyat_transfers_count: int = 0

    # «Сбор/копилка» — максимум уникальных отправителей P2P за окно N дней
    collective_fundraising_max_unique: int = 0

    # Доля поступлений от ранее невиданных отправителей (во второй половине периода)
    new_senders_share: float = 0.0

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

    # -------- новые метрики из разбора banki.ru-кейсов 2025–2026 --------
    _compute_banki_case_features(df, descriptions, feat)

    # evidence для отчёта -------------------------------------------
    feat.evidence = _build_evidence(df)
    return feat


def _compute_banki_case_features(
    df: pd.DataFrame,
    descriptions: pd.Series,
    feat: StatementFeatures,
) -> None:
    """Посчитать признаки, вытянутые из реальных кейсов 2025–2026.

    Метрики соответствуют пунктам МР ЦБ 16-МР / 11-МР и паттернам, которые
    массово всплывают в отзывах banki.ru (Сбер, Т-Банк, Ozon Bank, Альфа и др.).
    """

    # --- fast in/out: зачисление и списание в течение <= fast_inout_window_seconds ---
    from .constants import DEFAULT_THRESHOLDS  # избегаем циклического импорта при загрузке модуля

    window_sec = DEFAULT_THRESHOLDS.fast_inout_window_seconds
    sorted_df = df.sort_values(CANON_DATE).reset_index(drop=True)
    amounts = sorted_df[CANON_AMOUNT].to_numpy()
    times = sorted_df[CANON_DATE].to_numpy()

    pairs = 0
    income_total_count = int((amounts > 0).sum())
    for i in range(len(sorted_df) - 1):
        if amounts[i] <= 0 or amounts[i + 1] >= 0:
            continue
        dt_sec = (times[i + 1] - times[i]) / np.timedelta64(1, "s")
        if dt_sec <= window_sec:
            pairs += 1
    feat.fast_inout_pairs_count = int(pairs)
    if income_total_count > 0:
        feat.fast_inout_share = float(pairs) / float(income_total_count)

    # --- жизнеобеспечение (ЖКХ/связь/маркетплейсы) ---
    lifestyle_mask = (sorted_df[CANON_AMOUNT] < 0) & descriptions.loc[sorted_df.index].apply(
        lambda s: _matches_any(s, LIFESTYLE_KEYWORDS)
    )
    feat.lifestyle_payments_count = int(lifestyle_mask.sum())
    feat.has_lifestyle_payments = feat.lifestyle_payments_count > 0
    if feat.has_lifestyle_payments:
        last_lifestyle = sorted_df.loc[lifestyle_mask, CANON_DATE].max()
        last_date = sorted_df[CANON_DATE].max()
        feat.days_without_lifestyle = int((last_date - last_lifestyle).days)
    else:
        feat.days_without_lifestyle = feat.days_observed

    # --- круглосуточная активность ---
    hours = sorted_df[CANON_DATE].dt.hour
    feat.active_hours_span = int(hours.nunique())
    hours_by_day = sorted_df.groupby(sorted_df[CANON_DATE].dt.date)[CANON_DATE].apply(
        lambda s: s.dt.hour.nunique()
    )
    feat.active_hours_avg_per_day = float(hours_by_day.mean()) if not hours_by_day.empty else 0.0

    # --- СБП-вывод сразу после зачисления ---
    # Для каждого дня считаем долю дней, где после входящей операции в течение
    # часа следовал исходящий p2p/СБП во внешний банк.
    days_triggered = 0
    days_with_income = 0
    for _, grp in sorted_df.groupby(sorted_df[CANON_DATE].dt.date):
        grp = grp.sort_values(CANON_DATE)
        has_income = False
        triggered = False
        last_income_time: pd.Timestamp | None = None
        for _, row in grp.iterrows():
            amt = float(row[CANON_AMOUNT])
            desc = str(row[CANON_DESCRIPTION]).lower()
            ch = str(row[CANON_CHANNEL])
            ts = row[CANON_DATE]
            if amt > 0:
                has_income = True
                last_income_time = ts
            elif (
                amt < 0
                and last_income_time is not None
                and (ts - last_income_time).total_seconds() <= 3600
                and (ch == "p2p" or _matches_any(desc, EXTERNAL_BANK_HINTS))
            ):
                triggered = True
        if has_income:
            days_with_income += 1
            if triggered:
                days_triggered += 1
    if days_with_income > 0:
        feat.sbp_out_after_income_share = float(days_triggered) / float(days_with_income)

    # --- третьи лица вносят наличные ---
    third_party_cash_mask = (sorted_df[CANON_AMOUNT] > 0) & descriptions.loc[sorted_df.index].apply(
        lambda s: _matches_any(s, CASH_DEPOSIT_KEYWORDS)
    )
    feat.third_party_cash_deposits_count = int(third_party_cash_mask.sum())

    # --- переводы ИП/самозанятым ---
    ip_mask = (sorted_df[CANON_AMOUNT] < 0) & descriptions.loc[sorted_df.index].apply(
        lambda s: _matches_any(s, SELF_EMPLOYED_KEYWORDS)
    )
    feat.ip_samozanyat_transfers_count = int(ip_mask.sum())

    # --- «сбор/копилка»: макс. число уникальных входящих отправителей P2P за скользящее окно N дней ---
    window_days = DEFAULT_THRESHOLDS.collective_fundraising_window_days
    p2p_in = sorted_df[(sorted_df[CANON_CHANNEL] == "p2p") & (sorted_df[CANON_AMOUNT] > 0)].copy()
    if not p2p_in.empty:
        p2p_in["_cp"] = [
            _extract_counterparty(d, c)
            for d, c in zip(p2p_in[CANON_DESCRIPTION], p2p_in[CANON_COUNTERPARTY], strict=False)
        ]
        max_unique = 0
        ts_series = p2p_in[CANON_DATE].to_numpy()
        cp_series = p2p_in["_cp"].to_numpy()
        n = len(p2p_in)
        left = 0
        for right in range(n):
            window_start = ts_series[right] - np.timedelta64(window_days, "D")
            while ts_series[left] < window_start:
                left += 1
            max_unique = max(max_unique, len(set(cp_series[left : right + 1])))
        feat.collective_fundraising_max_unique = int(max_unique)

    # --- доля поступлений от новых отправителей (вторая половина периода) ---
    if not sorted_df.empty:
        total_days = feat.days_observed
        midpoint = sorted_df[CANON_DATE].min() + pd.Timedelta(days=total_days // 2)
        first_half = sorted_df[sorted_df[CANON_DATE] < midpoint]
        second_half = sorted_df[(sorted_df[CANON_DATE] >= midpoint) & (sorted_df[CANON_AMOUNT] > 0)]
        known = {
            _extract_counterparty(d, c)
            for d, c in zip(first_half[CANON_DESCRIPTION], first_half[CANON_COUNTERPARTY], strict=False)
        }
        known.discard("")
        if not second_half.empty:
            new_count = 0
            for d, c in zip(second_half[CANON_DESCRIPTION], second_half[CANON_COUNTERPARTY], strict=False):
                if _extract_counterparty(d, c) not in known:
                    new_count += 1
            feat.new_senders_share = float(new_count) / float(len(second_half))


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
