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
    BUDGET_FUNDS_KEYWORDS,
    BUSINESS_KEYWORDS,
    CANON_AMOUNT,
    CANON_CHANNEL,
    CANON_COUNTERPARTY,
    CANON_DATE,
    CANON_DESCRIPTION,
    CARD_PURCHASE_KEYWORDS,
    CASH_DEPOSIT_KEYWORDS,
    CASH_WITHDRAWAL_KEYWORDS,
    CFA_DIGITAL_ASSETS_KEYWORDS,
    CROSS_BORDER_KEYWORDS,
    CRYPTO_KEYWORDS,
    DROPPERS_REGISTRY_KEYWORDS,
    EXTERNAL_BANK_HINTS,
    EXTERNAL_BANK_NAMES,
    FATF_HIGH_RISK_KEYWORDS,
    GAMBLING_KEYWORDS,
    GIFT_LOAN_KEYWORDS,
    LIFESTYLE_KEYWORDS,
    NFC_ATM_KEYWORDS,
    PENSION_KEYWORDS,
    PRECIOUS_METALS_KEYWORDS,
    REJECT_KEYWORDS,
    SALARY_KEYWORDS,
    SELF_EMPLOYED_KEYWORDS,
    SELF_TRANSFER_KEYWORDS,
    THIRD_PARTY_SETTLEMENT_KEYWORDS,
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

    # ---------- вторая волна признаков (100+ кейсов banki.ru 2025–2026) ----------
    round_amounts_share: float = 0.0
    identical_amount_max_repeats: int = 0
    salary_day_drain_ratio: float = 0.0
    dormant_days_before_spike: int = 0
    multi_bank_fanout_max: int = 0
    cross_border_transfers_count: int = 0
    avg_p2p_amount: float = 0.0
    atm_cashout_after_income_ratio: float = 0.0
    one_dominant_sender_share: float = 0.0
    rejected_operations_count: int = 0
    card_purchases_count: int = 0

    # ---------- третья волна: антифрод-системы + комплаенс 2025–2026 ----------
    structuring_sub_threshold_count: int = 0
    smurfing_same_receiver_max_ops: int = 0
    smurfing_same_receiver_max_sum: float = 0.0
    nfc_atm_ops_count: int = 0
    droppers_registry_hits_count: int = 0
    le_to_individual_regular_count: int = 0
    precious_metals_after_income_count: int = 0
    fatf_high_risk_transfers_count: int = 0
    gift_loan_abuse_count: int = 0
    gift_loan_abuse_share: float = 0.0
    velocity_per_minute_max: int = 0
    self_transfer_banks_unique: int = 0
    mirror_transfers_pairs_count: int = 0
    sbp_split_same_receiver_max_ops: int = 0

    # ---------- четвёртая волна: «скрытые» сигналы антифрод-систем ----------
    return_diff_bank_count: int = 0
    cfa_digital_assets_count: int = 0
    third_party_settlement_count: int = 0
    pensioner_drain_share: float = 0.0
    pensioner_incomes_count: int = 0
    weekend_turnover_share: float = 0.0
    deep_night_ratio: float = 0.0
    benford_chi2: float = 0.0
    benford_sample_size: int = 0
    one_time_counterparty_ratio: float = 0.0
    one_time_counterparty_unique: int = 0
    multi_employer_salary_count: int = 0
    cash_split_same_day_max: int = 0
    outgoing_only_days_share: float = 0.0
    outgoing_only_days_total: int = 0
    budget_funds_fast_transit_count: int = 0
    budget_funds_incomes_count: int = 0

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
    _compute_banki_case_features_v2(df, descriptions, feat)
    _compute_antifraud_features_v3(df, descriptions, feat)
    _compute_antifraud_features_v4(df, descriptions, feat)

    # evidence для отчёта -------------------------------------------
    feat.evidence = _build_evidence(df)
    return feat


def _compute_banki_case_features_v2(
    df: pd.DataFrame,
    descriptions: pd.Series,
    feat: StatementFeatures,
) -> None:
    """Вторая волна признаков: разбор 100+ отзывов banki.ru 2025–2026.

    Паттерны:
      * круглые суммы (5k/10k/50k) и повторы одинаковых сумм
      * salary-day drain (>70 % зарплаты уходит в тот же день)
      * dormant → spike (возвращение после длинной паузы)
      * веер входящих из разных банков за 7 дней
      * трансграничные переводы (СНГ/SWIFT)
      * низкий средний чек P2P
      * снятие наличных в тот же день после зачисления
      * доминирование одного отправителя (>60 %)
      * отказы/возвраты антифрода в описаниях
      * отсутствие POS/онлайн-покупок
    """
    from .constants import DEFAULT_THRESHOLDS

    sorted_df = df.sort_values(CANON_DATE).reset_index(drop=True)
    # выравниваем описания к новому порядку индексов
    desc_l = descriptions.reset_index(drop=True).reindex(sorted_df.index).fillna("")
    income_mask = sorted_df[CANON_AMOUNT] > 0
    expense_mask = sorted_df[CANON_AMOUNT] < 0

    # --- круглые суммы среди входящих ---
    incoming_amounts = sorted_df.loc[income_mask, CANON_AMOUNT].to_numpy()
    if incoming_amounts.size:
        round_mask_any = np.array(
            [_is_round_amount(float(x)) for x in incoming_amounts], dtype=bool
        )
        feat.round_amounts_share = float(round_mask_any.mean())

        # --- одинаковые суммы повторяются ---
        amount_series = pd.Series(np.round(incoming_amounts, 2))
        value_counts = amount_series.value_counts()
        feat.identical_amount_max_repeats = int(value_counts.iloc[0]) if not value_counts.empty else 0

    # --- salary-day drain: по каждой крупной входящей смотрим, сколько ушло за ≤24ч ---
    salary_in = sorted_df.loc[income_mask & (sorted_df[CANON_AMOUNT] >= 20_000)]
    drains: list[float] = []
    for _, row in salary_in.iterrows():
        start_ts = row[CANON_DATE]
        end_ts = start_ts + pd.Timedelta(hours=24)
        out_24h = -sorted_df.loc[
            expense_mask & (sorted_df[CANON_DATE] >= start_ts) & (sorted_df[CANON_DATE] <= end_ts),
            CANON_AMOUNT,
        ].sum()
        if row[CANON_AMOUNT] > 0:
            drains.append(min(1.0, float(out_24h) / float(row[CANON_AMOUNT])))
    if drains:
        feat.salary_day_drain_ratio = float(np.mean(drains))

    # --- dormant → spike ---
    if len(sorted_df) >= 2:
        deltas = np.diff(sorted_df[CANON_DATE].to_numpy()) / np.timedelta64(1, "D")
        if deltas.size:
            feat.dormant_days_before_spike = int(np.max(deltas))

    # --- веер разных банков в окне N дней (по ключевым словам в описании) ---
    bank_hints = (
        ("сбер", "sber"),
        ("тиньк", "т-банк", "тбанк", "tinkoff"),
        ("альфа", "alfa"),
        ("втб", "vtb"),
        ("газпром", "gazprom"),
        ("озон", "ozon"),
        ("мтс", "mts"),
        ("райф", "raiff"),
        ("почта банк", "pochta"),
        ("уралсиб",),
        ("ренессанс",),
        ("яндекс", "yandex"),
        ("совком",),
        ("отп", "otp"),
        ("цифра",),
    )

    def _detect_bank(s: str) -> str | None:
        s_low = s.lower()
        for idx, hints in enumerate(bank_hints):
            for h in hints:
                if h in s_low:
                    return f"bank_{idx}"
        return None

    income_rows = sorted_df.loc[income_mask].copy().reset_index(drop=True)
    if not income_rows.empty:
        income_rows["_bank"] = [
            _detect_bank(str(d)) for d in income_rows[CANON_DESCRIPTION]
        ]
        income_rows = income_rows[income_rows["_bank"].notna()].reset_index(drop=True)
        if not income_rows.empty:
            window = pd.Timedelta(days=DEFAULT_THRESHOLDS.multi_bank_fanout_window_days)
            ts = income_rows[CANON_DATE].to_numpy()
            banks = income_rows["_bank"].to_numpy()
            max_unique = 0
            left = 0
            for right in range(len(income_rows)):
                while ts[right] - ts[left] > window:
                    left += 1
                max_unique = max(max_unique, len(set(banks[left : right + 1])))
            feat.multi_bank_fanout_max = int(max_unique)

    # --- трансграничные переводы ---
    cross_mask = desc_l.apply(lambda s: _matches_any(s, CROSS_BORDER_KEYWORDS))
    feat.cross_border_transfers_count = int(cross_mask.sum())

    # --- средний чек P2P ---
    p2p_mask_v2 = sorted_df[CANON_CHANNEL].eq("p2p")
    p2p_amounts = sorted_df.loc[p2p_mask_v2, CANON_AMOUNT].abs()
    if not p2p_amounts.empty:
        feat.avg_p2p_amount = float(p2p_amounts.mean())

    # --- ATM-снятие после зачисления (доля входящих, снятая в тот же день) ---
    atm_mask = expense_mask & (
        sorted_df[CANON_CHANNEL].eq("cash")
        | desc_l.apply(lambda s: _matches_any(s, CASH_WITHDRAWAL_KEYWORDS))
    )
    if income_mask.any():
        day_groups = sorted_df.groupby(sorted_df[CANON_DATE].dt.date)
        day_ratios: list[float] = []
        for _, grp in day_groups:
            day_in = grp.loc[grp[CANON_AMOUNT] > 0, CANON_AMOUNT].sum()
            if day_in <= 0:
                continue
            day_atm = -grp.loc[atm_mask.reindex(grp.index, fill_value=False), CANON_AMOUNT].sum()
            day_ratios.append(min(1.0, float(day_atm) / float(day_in)))
        if day_ratios:
            feat.atm_cashout_after_income_ratio = float(np.mean(day_ratios))

    # --- доминирование одного отправителя ---
    incoming = sorted_df.loc[income_mask]
    if not incoming.empty:
        cps = [
            _extract_counterparty(d, c)
            for d, c in zip(incoming[CANON_DESCRIPTION], incoming[CANON_COUNTERPARTY], strict=False)
        ]
        cps_filtered = [c for c in cps if c]
        if cps_filtered:
            cp_amounts = pd.Series(incoming[CANON_AMOUNT].to_numpy(), index=cps)
            totals = cp_amounts.groupby(level=0).sum()
            top_cp = totals.idxmax()
            if top_cp:
                feat.one_dominant_sender_share = float(totals.loc[top_cp]) / max(
                    1.0, float(totals.sum())
                )

    # --- отказы/возвраты ---
    reject_mask = desc_l.apply(lambda s: _matches_any(s, REJECT_KEYWORDS))
    feat.rejected_operations_count = int(reject_mask.sum())

    # --- POS/онлайн-покупки ---
    card_mask = desc_l.apply(lambda s: _matches_any(s, CARD_PURCHASE_KEYWORDS)) | sorted_df[
        CANON_CHANNEL
    ].eq("card") | sorted_df[CANON_CHANNEL].eq("online")
    feat.card_purchases_count = int((card_mask & expense_mask).sum())


def _is_round_amount(x: float, tolerance: float = 0.01) -> bool:
    """True если сумма «красивая» (кратна 1k/5k/10k/50k/100k)."""
    ax = abs(x)
    if ax < 100:
        return False
    for base in (100_000.0, 50_000.0, 10_000.0, 5_000.0, 1_000.0):
        remainder = ax % base
        if remainder < tolerance or base - remainder < tolerance:
            return True
    return False


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


def _compute_antifraud_features_v3(
    df: pd.DataFrame,
    descriptions: pd.Series,
    feat: StatementFeatures,
) -> None:
    """Третья волна признаков: антифрод-системы и комплаенс-правила 2025–2026.

    Покрывает сценарии, которые напрямую ловят FICO Falcon, SAS AML,
    ЦФТ Антифрод, BSS Fraud и комплаенс-контроль ЦБ РФ:
      * structuring (FATF + 115-ФЗ ст.6)
      * smurfing по одному получателю (FATF)
      * NFC-банкоматы (ОД-2506, действует с 01.01.2026)
      * реестр дропперов ФинЦЕРТ (Указание 6748-У)
      * регулярные переводы ЮЛ/ИП → физ.лицу (375-П ред. 2025)
      * драгметаллы после поступления (375-П ред. 2025)
      * переводы в юрисдикции высокого риска (FATF)
      * злоупотребление «подарок/займ» (МР 4-МР)
      * velocity-правила (FICO Falcon)
      * self-transfer fanout (FATF layering)
      * mirror-transfers (FATF layering)
      * СБП-split одному получателю (обход лимита 100k ₽/сутки)
    """
    from .constants import DEFAULT_THRESHOLDS

    th = DEFAULT_THRESHOLDS
    if df.empty:
        return

    sorted_df = df.sort_values(CANON_DATE).reset_index(drop=True)
    desc_l = descriptions.reset_index(drop=True).reindex(sorted_df.index).fillna("")
    amounts = sorted_df[CANON_AMOUNT].to_numpy()
    abs_amounts = np.abs(amounts)
    times = sorted_df[CANON_DATE].to_numpy()

    # --- structuring: суммы под порогом обязательного контроля 600k/1M ₽ ---
    structuring_mask = (
        ((abs_amounts >= th.structuring_lower_bound_rub) & (abs_amounts <= th.structuring_upper_bound_rub))
        | ((abs_amounts >= th.structuring_lower_bound_mln) & (abs_amounts <= th.structuring_upper_bound_mln))
    )
    feat.structuring_sub_threshold_count = int(structuring_mask.sum())

    # --- smurfing: N+ переводов одному получателю за сутки ---
    expense_mask = amounts < 0
    expense_df = sorted_df.loc[expense_mask].copy()
    if not expense_df.empty:
        expense_df["_cp"] = [
            _extract_counterparty(d, c)
            for d, c in zip(expense_df[CANON_DESCRIPTION], expense_df[CANON_COUNTERPARTY], strict=False)
        ]
        expense_df["_day"] = expense_df[CANON_DATE].dt.date
        expense_df = expense_df[expense_df["_cp"] != ""]
        if not expense_df.empty:
            grp = expense_df.groupby(["_cp", "_day"])[CANON_AMOUNT].agg(["count", lambda s: float(s.abs().sum())])
            grp.columns = ["ops", "sum"]
            if not grp.empty:
                feat.smurfing_same_receiver_max_ops = int(grp["ops"].max())
                feat.smurfing_same_receiver_max_sum = float(grp["sum"].max())

    # --- NFC-банкоматы (ОД-2506) ---
    nfc_mask = desc_l.apply(lambda s: _matches_any(s, NFC_ATM_KEYWORDS))
    feat.nfc_atm_ops_count = int(nfc_mask.sum())

    # --- ФинЦЕРТ / реестр дропперов ---
    dropper_mask = desc_l.apply(lambda s: _matches_any(s, DROPPERS_REGISTRY_KEYWORDS))
    feat.droppers_registry_hits_count = int(dropper_mask.sum())

    # --- регулярные переводы ЮЛ/ИП физ.лицу, не зарплата ---
    le_desc_mask = desc_l.apply(
        lambda s: (_matches_any(s, SELF_EMPLOYED_KEYWORDS) or _matches_any(s, BUSINESS_KEYWORDS))
        and not _matches_any(s, SALARY_KEYWORDS)
    )
    le_incoming_mask = (sorted_df[CANON_AMOUNT] > 0) & le_desc_mask
    # Берём только входящие по разным датам, а не точные повторы.
    if le_incoming_mask.any():
        le_sub = sorted_df.loc[le_incoming_mask]
        unique_days = le_sub[CANON_DATE].dt.date.nunique()
        feat.le_to_individual_regular_count = int(unique_days)

    # --- драгметаллы сразу после поступления (в течение 3 дней) ---
    precious_mask = desc_l.apply(lambda s: _matches_any(s, PRECIOUS_METALS_KEYWORDS)) & (sorted_df[CANON_AMOUNT] < 0)
    if precious_mask.any():
        income_ts = sorted_df.loc[amounts > 0, CANON_DATE].to_numpy()
        cnt = 0
        for ts in sorted_df.loc[precious_mask, CANON_DATE]:
            ts64 = np.datetime64(ts)
            window = (income_ts <= ts64) & (income_ts >= ts64 - np.timedelta64(3, "D"))
            if window.any():
                cnt += 1
        feat.precious_metals_after_income_count = int(cnt)

    # --- FATF high-risk юрисдикции ---
    fatf_mask = desc_l.apply(lambda s: _matches_any(s, FATF_HIGH_RISK_KEYWORDS))
    feat.fatf_high_risk_transfers_count = int(fatf_mask.sum())

    # --- подарок/займ/возврат долга: подсчёт и доля среди входящих P2P ---
    gift_mask = desc_l.apply(lambda s: _matches_any(s, GIFT_LOAN_KEYWORDS))
    feat.gift_loan_abuse_count = int(gift_mask.sum())
    p2p_in_mask = (sorted_df[CANON_CHANNEL] == "p2p") & (amounts > 0)
    p2p_in_count = int(p2p_in_mask.sum())
    if p2p_in_count > 0:
        gift_in_count = int((gift_mask & p2p_in_mask).sum())
        feat.gift_loan_abuse_share = float(gift_in_count) / float(p2p_in_count)

    # --- velocity: макс. число операций в одну минуту ---
    if len(sorted_df) >= 2:
        minute_bucket = sorted_df[CANON_DATE].dt.floor("min")
        per_min = minute_bucket.value_counts()
        feat.velocity_per_minute_max = int(per_min.max()) if not per_min.empty else 0

    # --- self-transfer fanout: переводы «себе» в разные банки ---
    self_mask = desc_l.apply(lambda s: _matches_any(s, SELF_TRANSFER_KEYWORDS)) & (amounts < 0)
    if self_mask.any():
        self_descs = desc_l.loc[self_mask]
        banks_seen: set[str] = set()
        for s in self_descs:
            for bank in EXTERNAL_BANK_NAMES:
                if bank in s:
                    banks_seen.add(bank)
                    break
        feat.self_transfer_banks_unique = int(len(banks_seen))

    # --- mirror transfers: пары «туда-сюда» с одним контрагентом ---
    p2p_df = sorted_df[sorted_df[CANON_CHANNEL] == "p2p"].copy()
    if not p2p_df.empty:
        p2p_df["_cp"] = [
            _extract_counterparty(d, c)
            for d, c in zip(p2p_df[CANON_DESCRIPTION], p2p_df[CANON_COUNTERPARTY], strict=False)
        ]
        mirror_pairs = 0
        for cp, sub in p2p_df.groupby("_cp"):
            if not cp:
                continue
            has_in = (sub[CANON_AMOUNT] > 0).any()
            has_out = (sub[CANON_AMOUNT] < 0).any()
            if has_in and has_out:
                mirror_pairs += min((sub[CANON_AMOUNT] > 0).sum(), (sub[CANON_AMOUNT] < 0).sum())
        feat.mirror_transfers_pairs_count = int(mirror_pairs)

    # --- СБП-split одному получателю (в пределах окна часов) ---
    if not expense_df.empty and "_cp" in expense_df.columns:
        sbp_out_mask = expense_df[CANON_CHANNEL].eq("p2p") | expense_df[CANON_DESCRIPTION].str.lower().str.contains(
            "сбп", na=False
        )
        sbp_sub = expense_df.loc[sbp_out_mask]
        if not sbp_sub.empty:
            max_ops = 0
            window = pd.Timedelta(hours=th.sbp_split_window_hours)
            for _cp, grp in sbp_sub.groupby("_cp"):
                if not _cp:
                    continue
                ts = grp[CANON_DATE].sort_values().to_numpy()
                left = 0
                for right in range(len(ts)):
                    while ts[right] - ts[left] > window:
                        left += 1
                    max_ops = max(max_ops, right - left + 1)
            feat.sbp_split_same_receiver_max_ops = int(max_ops)

    # Защищаемся от «сломанных» numpy типов в суммах
    _ = times  # numpy array already kept for potential extensions


# ------ четвёртая волна: «скрытые» сигналы антифрод-систем 2025–2026 ------


def _compute_antifraud_features_v4(
    df: pd.DataFrame,
    descriptions: pd.Series,
    feat: StatementFeatures,
) -> None:
    """Четвёртая волна признаков: «скрытые» сигналы из внутренних антифрод-систем.

    Источники:
      * Положение ЦБ РФ 860-П (ред. 18.06.2025) — признаки 1121/1137/1192
      * Внутренние правила Сбербанка 2025–2026 (защита пенсионеров)
      * Поведенческие сценарии SAS EC4 / Feedzai / FICO Falcon
      * Forensic AML — распределение Бенфорда (закон первой цифры)
      * NICE Actimize SAM — mule-типаж (одноразовые контрагенты)
    """
    from .constants import DEFAULT_THRESHOLDS

    th = DEFAULT_THRESHOLDS
    if df.empty:
        return

    sorted_df = df.sort_values(CANON_DATE).reset_index(drop=True)
    desc_l = descriptions.reset_index(drop=True).reindex(sorted_df.index).fillna("")
    amounts = sorted_df[CANON_AMOUNT].to_numpy()
    abs_amounts = np.abs(amounts)

    # --- 860-П п.1121: возврат контрагенту через другой банк ---
    # Ищем пары (входящий → исходящий тому же контрагенту в другой банк в течение N часов).
    return_diff_bank_count = 0
    if len(sorted_df) >= 2:
        df_enriched = sorted_df.copy()
        df_enriched["_cp"] = [
            _extract_counterparty(d, c)
            for d, c in zip(df_enriched[CANON_DESCRIPTION], df_enriched[CANON_COUNTERPARTY], strict=False)
        ]
        df_enriched["_bank"] = desc_l.apply(
            lambda s: next((b for b in EXTERNAL_BANK_NAMES if b in s), "")
        )
        # Для каждой входящей операции ищем исходящую тому же контрагенту в другом банке.
        incoming = df_enriched[df_enriched[CANON_AMOUNT] > 0]
        for _, row in incoming.iterrows():
            cp = row["_cp"]
            bank_in = row["_bank"]
            if not cp or not bank_in:
                continue
            ts = row[CANON_DATE]
            later = df_enriched[
                (df_enriched[CANON_DATE] > ts)
                & (df_enriched[CANON_DATE] <= ts + pd.Timedelta(hours=72))
                & (df_enriched[CANON_AMOUNT] < 0)
                & (df_enriched["_cp"] == cp)
                & (df_enriched["_bank"] != "")
                & (df_enriched["_bank"] != bank_in)
            ]
            if not later.empty:
                return_diff_bank_count += 1
    feat.return_diff_bank_count = int(return_diff_bank_count)

    # --- 860-П п.1137: операции с ЦФА / цифровыми правами ---
    cfa_mask = desc_l.apply(lambda s: _matches_any(s, CFA_DIGITAL_ASSETS_KEYWORDS))
    feat.cfa_digital_assets_count = int(cfa_mask.sum())

    # --- 860-П п.1192: расчёт за третье лицо ---
    third_party_mask = desc_l.apply(lambda s: _matches_any(s, THIRD_PARTY_SETTLEMENT_KEYWORDS))
    feat.third_party_settlement_count = int(third_party_mask.sum())

    # --- Сбер: пенсионный drain ---
    pension_in_mask = (amounts > 0) & desc_l.apply(lambda s: _matches_any(s, PENSION_KEYWORDS))
    feat.pensioner_incomes_count = int(pension_in_mask.sum())
    if feat.pensioner_incomes_count > 0:
        window = pd.Timedelta(hours=th.pensioner_drain_window_hours)
        drained_sum = 0.0
        total_pension = 0.0
        for idx in np.where(pension_in_mask)[0]:
            pension_amount = float(amounts[idx])
            pension_ts = sorted_df.loc[idx, CANON_DATE]
            total_pension += pension_amount
            mask_after = (
                (sorted_df[CANON_DATE] > pension_ts)
                & (sorted_df[CANON_DATE] <= pension_ts + window)
                & (sorted_df[CANON_AMOUNT] < 0)
            )
            drained = float(-sorted_df.loc[mask_after, CANON_AMOUNT].sum())
            drained_sum += min(drained, pension_amount)
        if total_pension > 0:
            feat.pensioner_drain_share = float(drained_sum / total_pension)

    # --- SAS/Feedzai: доминирование выходных ---
    weekdays = sorted_df[CANON_DATE].dt.dayofweek  # 0=Mon .. 6=Sun
    weekend_mask = weekdays >= 5
    total_abs = float(abs_amounts.sum())
    if total_abs > 0:
        weekend_abs = float(abs_amounts[weekend_mask.to_numpy()].sum())
        feat.weekend_turnover_share = weekend_abs / total_abs

    # --- FICO Falcon: глубокая ночь 02:00–05:00 ---
    hours = sorted_df[CANON_DATE].dt.hour
    deep_night_mask = (hours >= 2) & (hours < 5)
    if len(sorted_df) > 0:
        feat.deep_night_ratio = float(deep_night_mask.sum()) / float(len(sorted_df))

    # --- Forensic AML: закон Бенфорда по P2P-суммам ---
    # Распределение Бенфорда: P(d) = log10(1 + 1/d) для d ∈ {1..9}
    p2p_abs = abs_amounts[(sorted_df[CANON_CHANNEL].to_numpy() == "p2p") & (abs_amounts >= 10)]
    if len(p2p_abs) >= th.benford_min_ops:
        first_digits = np.array([int(str(int(x))[0]) for x in p2p_abs if int(x) > 0])
        if len(first_digits) >= th.benford_min_ops:
            expected_pct = np.array([np.log10(1.0 + 1.0 / d) for d in range(1, 10)])
            observed_pct = np.array(
                [float((first_digits == d).sum()) / len(first_digits) for d in range(1, 10)]
            )
            # Chi-squared (умножаем на n, чтобы получить тест-статистику)
            with np.errstate(divide="ignore", invalid="ignore"):
                chi2 = float(
                    len(first_digits)
                    * np.nansum((observed_pct - expected_pct) ** 2 / expected_pct)
                )
            feat.benford_chi2 = chi2
            feat.benford_sample_size = int(len(first_digits))

    # --- NICE Actimize: доля одноразовых контрагентов ---
    all_cp_strs = [
        _extract_counterparty(d, c)
        for d, c in zip(sorted_df[CANON_DESCRIPTION], sorted_df[CANON_COUNTERPARTY], strict=False)
    ]
    cp_series = pd.Series([c for c in all_cp_strs if c])
    if len(cp_series) > 0:
        cp_counts = cp_series.value_counts()
        unique_cp = int(len(cp_counts))
        one_time_cp = int((cp_counts == 1).sum())
        feat.one_time_counterparty_unique = unique_cp
        if unique_cp > 0:
            feat.one_time_counterparty_ratio = float(one_time_cp) / float(unique_cp)

    # --- Несколько работодателей одновременно ---
    salary_mask = (amounts > 0) & desc_l.apply(lambda s: _matches_any(s, SALARY_KEYWORDS))
    if salary_mask.any():
        salary_cps = {
            _extract_counterparty(d, c)
            for d, c in zip(
                sorted_df.loc[salary_mask, CANON_DESCRIPTION],
                sorted_df.loc[salary_mask, CANON_COUNTERPARTY],
                strict=False,
            )
        }
        salary_cps.discard("")
        feat.multi_employer_salary_count = int(len(salary_cps))

    # --- Дробление внесения наличных в один день ---
    cash_deposit_mask = (amounts > 0) & desc_l.apply(lambda s: _matches_any(s, CASH_DEPOSIT_KEYWORDS))
    if cash_deposit_mask.any():
        per_day = sorted_df.loc[cash_deposit_mask].groupby(
            sorted_df.loc[cash_deposit_mask, CANON_DATE].dt.date
        ).size()
        feat.cash_split_same_day_max = int(per_day.max()) if not per_day.empty else 0

    # --- Чистый отток: дни только с исходящими операциями ---
    day_groups = sorted_df.groupby(sorted_df[CANON_DATE].dt.date)
    outgoing_only = 0
    total_days_with_activity = 0
    for _, grp in day_groups:
        total_days_with_activity += 1
        has_income = (grp[CANON_AMOUNT] > 0).any()
        has_expense = (grp[CANON_AMOUNT] < 0).any()
        if has_expense and not has_income:
            outgoing_only += 1
    feat.outgoing_only_days_total = int(outgoing_only)
    if total_days_with_activity >= th.outgoing_only_days_min_days:
        feat.outgoing_only_days_share = float(outgoing_only) / float(total_days_with_activity)

    # --- Бюджетные средства → быстрый транзит ---
    budget_in_mask = (amounts > 0) & desc_l.apply(lambda s: _matches_any(s, BUDGET_FUNDS_KEYWORDS))
    feat.budget_funds_incomes_count = int(budget_in_mask.sum())
    if feat.budget_funds_incomes_count > 0:
        window = pd.Timedelta(hours=th.budget_transit_window_hours)
        fast_count = 0
        for idx in np.where(budget_in_mask)[0]:
            budget_amount = float(amounts[idx])
            budget_ts = sorted_df.loc[idx, CANON_DATE]
            mask_after = (
                (sorted_df[CANON_DATE] > budget_ts)
                & (sorted_df[CANON_DATE] <= budget_ts + window)
                & (sorted_df[CANON_AMOUNT] < 0)
            )
            drained = float(-sorted_df.loc[mask_after, CANON_AMOUNT].sum())
            if drained >= 0.5 * budget_amount:
                fast_count += 1
        feat.budget_funds_fast_transit_count = int(fast_count)


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
