"""Гибридная rule-based + ML оценка риска блокировки по 115-ФЗ.

Логика работы
-------------

1. По :class:`~riskguard.feature_engineering.StatementFeatures` rule-based
   движок определяет, какие правила из :data:`~riskguard.constants.RULES`
   сработали и с какой «яркостью» (жёлтая / красная зона).  Для каждого
   правила считается вклад в итоговый балл по формуле
   ``weight * intensity``, где ``intensity ∈ {0, 0.5, 1}``.
2. Суммарный балл пропускается через *сигмоид*, чтобы получить вероятность
   блокировки в диапазоне 0..1.  Итоговый ``risk_score`` — это проценты.
3. Опционально, если подгружена CatBoost-модель, её вероятность смешивается
   со скорингом rule-движка (по умолчанию ``alpha=0.4``).
4. Для каждого сработавшего правила формируется человекочитаемый флаг с
   объяснением и конкретным планом действий — это ядро ценности продукта:
   «не пугаем, а помогаем».

Все пороги настраиваются через :class:`~riskguard.constants.Thresholds` —
в том числе через «Режим максимальной защиты» в UI.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .constants import (
    DEFAULT_THRESHOLDS,
    LEVEL_COLORS,
    LEVEL_LABELS_RU,
    RULES,
    RiskLevel,
    RuleSpec,
    Thresholds,
)
from .feature_engineering import StatementFeatures

# ----------------------------- dataclass --------------------------------


@dataclass
class RiskFlag:
    """Один сработавший флаг риска с контекстом и рекомендациями."""

    rule_id: str
    name: str
    category: str
    severity: str  # "yellow" | "red"
    weight: float
    contribution: float
    law: str
    why_dangerous: str
    action_hint: str
    case_reference: str
    evidence: list[dict] = field(default_factory=list)
    metric_value: float | None = None
    metric_threshold: float | None = None
    message: str = ""

    @property
    def color(self) -> str:
        return "#d1242f" if self.severity == "red" else "#f2a93b"


@dataclass
class RiskAssessment:
    """Итоговая оценка риска по выписке."""

    risk_score: float  # 0..100
    probability: float  # 0..1
    level: RiskLevel
    flags: list[RiskFlag]
    ml_probability: float | None = None
    rule_score: float = 0.0
    recommendations: list[str] = field(default_factory=list)
    summary: str = ""

    @property
    def level_label(self) -> str:
        return LEVEL_LABELS_RU[self.level]

    @property
    def level_color(self) -> str:
        return LEVEL_COLORS[self.level]


# ----------------------------- rule movement ---------------------------


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _intensity(value: float, yellow: float, red: float, reverse: bool = False) -> float:
    """Вернуть интенсивность срабатывания правила: 0 / 0.5 / 1.

    ``reverse=True`` означает, что правило срабатывает при *меньших* значениях
    метрики (например, ``residual_ratio`` — чем меньше, тем хуже).
    """
    if reverse:
        if value <= red:
            return 1.0
        if value <= yellow:
            return 0.5
        return 0.0
    if value >= red:
        return 1.0
    if value >= yellow:
        return 0.5
    return 0.0


def _severity_from_intensity(intensity: float) -> str:
    return "red" if intensity >= 1.0 else "yellow"


def _make_flag(
    spec: RuleSpec,
    intensity: float,
    value: float,
    threshold: float,
    message: str,
    evidence: list[dict] | None = None,
) -> RiskFlag:
    return RiskFlag(
        rule_id=spec.id,
        name=spec.name,
        category=spec.category,
        severity=_severity_from_intensity(intensity),
        weight=spec.weight,
        contribution=spec.weight * intensity,
        law=spec.law,
        why_dangerous=spec.why_dangerous,
        action_hint=spec.action_hint,
        case_reference=spec.case_reference,
        metric_value=value,
        metric_threshold=threshold,
        message=message,
        evidence=evidence or [],
    )


# ----------------------------- rule implementations --------------------


def _rule_p2p_daily(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(feat.p2p_max_per_day, th.p2p_per_day_yellow, th.p2p_per_day_red)
    if intensity == 0:
        return None
    spec = RULES["p2p_daily_spike"]
    msg = (
        f"В самый активный день обнаружено {feat.p2p_max_per_day} P2P-переводов — "
        f"это {'уже в красной зоне' if intensity == 1 else 'в жёлтой зоне'} "
        f"по массовым кейсам 2025–2026 (порог {th.p2p_per_day_red}+ — блокировка)."
    )
    return _make_flag(spec, intensity, feat.p2p_max_per_day, th.p2p_per_day_red, msg, feat.evidence.get("p2p_samples"))


def _rule_p2p_month(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(feat.p2p_last30d, th.p2p_30d_yellow, th.p2p_30d_red)
    if intensity == 0:
        return None
    spec = RULES["p2p_monthly_volume"]
    msg = (
        f"За последние 30 дней — {feat.p2p_last30d} P2P-операций "
        f"(порог внимания банка {th.p2p_30d_yellow}, критический {th.p2p_30d_red})."
    )
    return _make_flag(spec, intensity, feat.p2p_last30d, th.p2p_30d_red, msg, feat.evidence.get("p2p_samples"))


def _rule_p2p_counterparties(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.p2p_unique_counterparties,
        th.p2p_unique_counterparties_yellow,
        th.p2p_unique_counterparties_red,
    )
    if intensity == 0:
        return None
    spec = RULES["high_p2p_unique_counterparties"]
    msg = (
        f"У вас {feat.p2p_unique_counterparties} разных физ-контрагентов по P2P. "
        f"ЦБ считает аномалией >{th.p2p_unique_counterparties_yellow} за месяц."
    )
    return _make_flag(
        spec, intensity, feat.p2p_unique_counterparties, th.p2p_unique_counterparties_red, msg
    )


def _rule_transit(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    # Два индикатора: residual_ratio (меньше = хуже) и same_day_turnover_share (больше = хуже).
    residual_intensity = _intensity(
        feat.residual_ratio, th.transit_residual_ratio_yellow, th.transit_residual_ratio_red, reverse=True
    )
    same_day_intensity = _intensity(
        feat.same_day_turnover_share, th.same_day_turnover_share_yellow, th.same_day_turnover_share_red
    )
    intensity = max(residual_intensity, same_day_intensity)
    if intensity == 0:
        return None
    spec = RULES["transit_activity"]
    msg = (
        f"Остаток на конец периода — всего {feat.residual_ratio * 100:.1f}% от поступлений, "
        f"а в среднем {feat.same_day_turnover_share * 100:.0f}% средств уходят со счёта в день поступления. "
        f"Это классический паттерн транзита (положение 375-П)."
    )
    return _make_flag(spec, intensity, feat.residual_ratio, th.transit_residual_ratio_red, msg)


def _rule_large_income(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(feat.largest_income, th.large_income_rub_yellow, th.large_income_rub_red)
    if intensity == 0:
        return None
    spec = RULES["large_unexplained_income"]
    msg = (
        f"Максимальное поступление — {feat.largest_income:,.0f} ₽. "
        f"По 519-П банк обязан запросить документы по операциям >{th.large_income_rub_yellow:,.0f} ₽ "
        f"без зарплатного основания."
    ).replace(",", " ")
    return _make_flag(
        spec, intensity, feat.largest_income, th.large_income_rub_red, msg, feat.evidence.get("large_income_samples")
    )


def _rule_monthly_turnover(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.monthly_turnover, th.total_monthly_turnover_yellow, th.total_monthly_turnover_red
    )
    if intensity == 0:
        return None
    spec = RULES["large_unexplained_income"]  # тот же нормативный блок
    msg = (
        f"Месячный оборот по счёту — около {feat.monthly_turnover:,.0f} ₽. "
        f"Для личного счёта без подтверждённого дохода порог {th.total_monthly_turnover_yellow:,.0f} ₽ "
        f"считается повышенным."
    ).replace(",", " ")
    return _make_flag(spec, intensity, feat.monthly_turnover, th.total_monthly_turnover_red, msg)


def _rule_micro_tx(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.small_tx_per_day_max, th.small_tx_count_day_yellow, th.small_tx_count_day_red
    )
    if intensity == 0:
        return None
    spec = RULES["micro_tx_flood"]
    msg = (
        f"В один день пришло {feat.small_tx_per_day_max} мелких переводов (< "
        f"{th.small_tx_amount_rub:,.0f} ₽) — это паттерн нелегального терминала."
    ).replace(",", " ")
    return _make_flag(spec, intensity, feat.small_tx_per_day_max, th.small_tx_count_day_red, msg)


def _rule_hidden_business(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.incoming_unique_counterparties,
        th.business_incoming_unique_counterparties_yellow,
        th.business_incoming_unique_counterparties_red,
    )
    if intensity == 0 and feat.incoming_from_individuals_count < th.business_incoming_unique_counterparties_yellow:
        return None
    spec = RULES["hidden_business"]
    msg = (
        f"{feat.incoming_unique_counterparties} разных отправителей денег; "
        f"{feat.incoming_from_individuals_count} операций с назначением «за услугу/товар/работу» — "
        f"банк расценит как скрытое предпринимательство без ИП/самозанятости."
    )
    return _make_flag(
        spec,
        max(intensity, 0.5),
        feat.incoming_unique_counterparties,
        th.business_incoming_unique_counterparties_red,
        msg,
        feat.evidence.get("business_samples"),
    )


def _rule_crypto(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(feat.crypto_ops_count, th.crypto_ops_count_yellow, th.crypto_ops_count_red)
    if intensity == 0:
        return None
    spec = RULES["crypto_exchange"]
    msg = (
        f"Найдено {feat.crypto_ops_count} операций, похожих на крипто-обменники "
        f"(Bybit/Garantex/Bitpapa и т.п.). С 2024 банк автоматически помечает "
        f"такие цепочки как высокорисковые."
    )
    return _make_flag(
        spec, intensity, feat.crypto_ops_count, th.crypto_ops_count_red, msg, feat.evidence.get("crypto_samples")
    )


def _rule_cash(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(feat.cash_ratio, th.cash_ratio_yellow, th.cash_ratio_red)
    if intensity == 0:
        return None
    spec = RULES["high_cash_ratio"]
    msg = (
        f"Доля наличных операций — {feat.cash_ratio * 100:.0f}% от оборота. "
        f"МР ЦБ 19-МР: >30% уже считается подозрительным паттерном."
    )
    return _make_flag(spec, intensity, feat.cash_ratio, th.cash_ratio_red, msg, feat.evidence.get("cash_samples"))


def _rule_spike(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.turnover_spike_ratio, th.turnover_spike_ratio_yellow, th.turnover_spike_ratio_red
    )
    if intensity == 0:
        return None
    spec = RULES["turnover_spike"]
    msg = (
        f"Максимальный дневной оборот в {feat.turnover_spike_ratio:.1f} раза превышает медианный — "
        f"антифрод-модель банка это точно увидит."
    )
    return _make_flag(spec, intensity, feat.turnover_spike_ratio, th.turnover_spike_ratio_red, msg)


def _rule_161(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.new_counterparty_share, th.new_counterparty_share_yellow, th.new_counterparty_share_red
    )
    # ночной процент тоже усиливает
    if feat.night_tx_ratio > 0.2:
        intensity = max(intensity, 0.5)
    if intensity == 0:
        return None
    spec = RULES["fraud_overlap_161"]
    msg = (
        f"Доля новых контрагентов — {feat.new_counterparty_share * 100:.0f}%, "
        f"ночных операций — {feat.night_tx_ratio * 100:.0f}%. "
        f"Такое банк с 25.07.2024 может расценить как признаки 161-ФЗ (дроп)."
    )
    return _make_flag(spec, intensity, feat.new_counterparty_share, th.new_counterparty_share_red, msg)


def _rule_gambling(feat: StatementFeatures, _: Thresholds) -> RiskFlag | None:
    if feat.gambling_ops_count < 3:
        return None
    intensity = 0.5 if feat.gambling_ops_count < 15 else 1.0
    spec = RULES["gambling_ops"]
    msg = f"Найдено {feat.gambling_ops_count} операций с букмекерами/казино."
    return _make_flag(spec, intensity, feat.gambling_ops_count, 15, msg)


# ---------- правила, вытянутые из разбора banki.ru-кейсов 2025–2026 ----------


def _rule_fast_in_out(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(feat.fast_inout_share, th.fast_inout_share_yellow, th.fast_inout_share_red)
    if intensity == 0:
        return None
    spec = RULES["fast_in_out"]
    msg = (
        f"В {feat.fast_inout_share * 100:.0f}% случаев деньги уходили со счёта "
        f"быстрее, чем за {th.fast_inout_window_seconds} секунд после поступления "
        f"({feat.fast_inout_pairs_count} пар in→out). По МР 16-МР (п.4) это прямой признак транзита."
    )
    return _make_flag(spec, intensity, feat.fast_inout_share, th.fast_inout_share_red, msg)


def _rule_no_lifestyle(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    # Если наблюдение <14 дней, слишком мало данных, чтобы уверенно говорить.
    if feat.days_observed < 14:
        return None
    intensity = _intensity(
        feat.days_without_lifestyle, th.no_lifestyle_days_yellow, th.no_lifestyle_days_red
    )
    if intensity == 0:
        return None
    spec = RULES["no_lifestyle_payments"]
    msg = (
        f"Последние {feat.days_without_lifestyle} дн. по счёту не было платежей за "
        f"ЖКХ/связь/маркетплейсы/АЗС. МР 16-МР п.8 считает это маркером дроп-счёта."
    )
    return _make_flag(
        spec, intensity, feat.days_without_lifestyle, th.no_lifestyle_days_red, msg
    )


def _rule_round_the_clock(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.active_hours_span, th.round_clock_hours_yellow, th.round_clock_hours_red
    )
    if intensity == 0:
        return None
    spec = RULES["round_the_clock"]
    msg = (
        f"Активность по счёту охватывает {feat.active_hours_span} разных часов в сутках "
        f"(в среднем {feat.active_hours_avg_per_day:.1f} ч/день). "
        f"МР 16-МР п.5 говорит: круглосуточная активность — признак подозрительности."
    )
    return _make_flag(
        spec, intensity, feat.active_hours_span, th.round_clock_hours_red, msg
    )


def _rule_crypto_gambling_combo(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    if feat.crypto_ops_count < th.crypto_gambling_combo_threshold:
        return None
    if feat.gambling_ops_count < th.crypto_gambling_combo_threshold:
        return None
    # если сработало оба порога — сразу red
    spec = RULES["crypto_gambling_combo"]
    msg = (
        f"В выписке одновременно {feat.crypto_ops_count} крипто-операций и "
        f"{feat.gambling_ops_count} операций с букмекерами. "
        "По кейсу Сбербанка 2026 года это триггер на отключение дистанционного "
        "обслуживания без разблокировки."
    )
    return _make_flag(
        spec, 1.0, feat.crypto_ops_count + feat.gambling_ops_count,
        th.crypto_gambling_combo_threshold * 2, msg,
        (feat.evidence.get("crypto_samples") or []) + (feat.evidence.get("gambling_samples") or []),
    )


def _rule_sbp_out_after_income(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.sbp_out_after_income_share,
        th.sbp_out_after_income_share_yellow,
        th.sbp_out_after_income_share_red,
    )
    if intensity == 0:
        return None
    spec = RULES["sbp_out_after_income"]
    msg = (
        f"В {feat.sbp_out_after_income_share * 100:.0f}% дней с поступлениями деньги "
        f"в тот же час уходили через СБП в другой банк. Т-Банк в 2026 году массово "
        "блокировал такие сценарии."
    )
    return _make_flag(
        spec, intensity, feat.sbp_out_after_income_share, th.sbp_out_after_income_share_red, msg
    )


def _rule_third_party_cash(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.third_party_cash_deposits_count,
        th.third_party_cash_deposits_yellow,
        th.third_party_cash_deposits_red,
    )
    if intensity == 0:
        return None
    spec = RULES["third_party_cash_deposits"]
    msg = (
        f"На счёт {feat.third_party_cash_deposits_count} раз внесены наличные "
        "(или похожие зачисления). МР 11-МР (09.09.2025) прямо обязал банки "
        "углублённо проверять такие операции."
    )
    return _make_flag(
        spec, intensity, feat.third_party_cash_deposits_count, th.third_party_cash_deposits_red, msg
    )


def _rule_ip_samozanyat(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.ip_samozanyat_transfers_count,
        th.ip_samozanyat_transfers_yellow,
        th.ip_samozanyat_transfers_red,
    )
    if intensity == 0:
        return None
    spec = RULES["ip_samozanyat_transfers"]
    msg = (
        f"Переводов в сторону ИП/самозанятых — {feat.ip_samozanyat_transfers_count}. "
        "Сбер (кейс 13.08.2025) блокирует такие операции при отсутствии подтверждения."
    )
    return _make_flag(
        spec, intensity, feat.ip_samozanyat_transfers_count, th.ip_samozanyat_transfers_red, msg
    )


def _rule_collective_fundraising(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.collective_fundraising_max_unique,
        th.collective_fundraising_unique_yellow,
        th.collective_fundraising_unique_red,
    )
    if intensity == 0:
        return None
    spec = RULES["collective_fundraising"]
    msg = (
        f"За {th.collective_fundraising_window_days} дня(-ей) на счёт пришли деньги от "
        f"{feat.collective_fundraising_max_unique} разных физлиц. "
        "Т-Банк (кейс 25.02.2026) расценивает подобные «сборы» как подозрительные."
    )
    return _make_flag(
        spec, intensity, feat.collective_fundraising_max_unique,
        th.collective_fundraising_unique_red, msg,
    )


def _rule_new_senders_dominance(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    # Правило работает только когда есть достаточно данных для разделения на полупериоды.
    if feat.days_observed < 14:
        return None
    intensity = _intensity(
        feat.new_senders_share, th.new_senders_share_yellow, th.new_senders_share_red
    )
    if intensity == 0:
        return None
    spec = RULES["new_senders_dominance"]
    msg = (
        f"{feat.new_senders_share * 100:.0f}% поступлений во второй половине периода — от "
        "отправителей, которых раньше не было. С 25.07.2024 это признак 161-ФЗ."
    )
    return _make_flag(
        spec, intensity, feat.new_senders_share, th.new_senders_share_red, msg
    )


# ---------- правила, добавленные во второй волне (разбор 100+ кейсов banki.ru) ----------


def _rule_round_amounts_pattern(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    # малое количество входящих — не судим
    if feat.p2p_incoming_count < 5 and feat.income_total < 30_000:
        return None
    intensity = _intensity(
        feat.round_amounts_share, th.round_amounts_share_yellow, th.round_amounts_share_red
    )
    if intensity == 0:
        return None
    spec = RULES["round_amounts_pattern"]
    msg = (
        f"{feat.round_amounts_share * 100:.0f}% входящих поступлений — «ровные» суммы "
        "(кратные 1k/5k/10k/50k). По МР 16-МР п.2 это маркер автоматических отправок "
        "(обменник/миксер), а не живых физлиц."
    )
    return _make_flag(spec, intensity, feat.round_amounts_share, th.round_amounts_share_red, msg)


def _rule_identical_amount_repeats(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.identical_amount_max_repeats,
        th.identical_amount_repeats_yellow,
        th.identical_amount_repeats_red,
    )
    if intensity == 0:
        return None
    spec = RULES["identical_amount_repeats"]
    msg = (
        f"Одна и та же входящая сумма повторилась {feat.identical_amount_max_repeats} раз. "
        "Кейсы Ozon Bank и Цифра Банка 2026 — именно такие «дубли» триггерят 115-ФЗ."
    )
    return _make_flag(
        spec, intensity, feat.identical_amount_max_repeats, th.identical_amount_repeats_red, msg
    )


def _rule_salary_day_drain(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    if feat.salary_day_drain_ratio <= 0.0:
        return None
    intensity = _intensity(
        feat.salary_day_drain_ratio,
        th.salary_day_drain_ratio_yellow,
        th.salary_day_drain_ratio_red,
    )
    if intensity == 0:
        return None
    spec = RULES["salary_day_drain"]
    msg = (
        f"{feat.salary_day_drain_ratio * 100:.0f}% поступлений уходит со счёта в день "
        "зачисления. МР 16-МР п.6 считает это признаком транзитного счёта."
    )
    return _make_flag(
        spec, intensity, feat.salary_day_drain_ratio, th.salary_day_drain_ratio_red, msg
    )


def _rule_dormant_then_active(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    # В коротких выписках (<30 дней) пауза ничего не значит.
    if feat.days_observed < 30:
        return None
    intensity = _intensity(
        feat.dormant_days_before_spike, th.dormant_days_yellow, th.dormant_days_red
    )
    if intensity == 0:
        return None
    # пауза опасна, только если после неё реально шла активность (tx_count > 5).
    if feat.tx_count < 5:
        return None
    spec = RULES["dormant_then_active"]
    msg = (
        f"В выписке есть «пауза» в {feat.dormant_days_before_spike} дней без операций, "
        "после которой снова пошла активность. Сбер (2026) блокирует такие счета как "
        "потенциально скомпрометированные."
    )
    return _make_flag(
        spec, intensity, feat.dormant_days_before_spike, th.dormant_days_red, msg
    )


def _rule_multi_bank_fanout(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.multi_bank_fanout_max, th.multi_bank_fanout_yellow, th.multi_bank_fanout_red
    )
    if intensity == 0:
        return None
    spec = RULES["multi_bank_fanout"]
    msg = (
        f"За {th.multi_bank_fanout_window_days} дней на счёт пришли поступления из "
        f"{feat.multi_bank_fanout_max} разных банков. Это паттерн «сбор/копилка», "
        "на который ориентируется антифрод Т-Банка и Ozon Bank."
    )
    return _make_flag(
        spec, intensity, feat.multi_bank_fanout_max, th.multi_bank_fanout_red, msg
    )


def _rule_cross_border_transfers(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.cross_border_transfers_count,
        th.cross_border_transfers_yellow,
        th.cross_border_transfers_red,
    )
    if intensity == 0:
        return None
    spec = RULES["cross_border_transfers"]
    msg = (
        f"В выписке {feat.cross_border_transfers_count} операций с признаками СНГ/SWIFT "
        "(Kaspi, Halyk, Айыл Банк и т.п.). В 2025 Сбер и ВТБ массово блокируют такие "
        "переводы по 173-ФЗ и 115-ФЗ."
    )
    return _make_flag(
        spec, intensity, feat.cross_border_transfers_count, th.cross_border_transfers_red, msg
    )


def _rule_very_low_avg_amount(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    if feat.p2p_count < th.very_low_avg_amount_min_ops:
        return None
    if feat.avg_p2p_amount <= 0:
        return None
    # Здесь меньше — хуже, поэтому интенсивность считаем «наоборот».
    if feat.avg_p2p_amount <= th.very_low_avg_amount_red:
        intensity = 1.0
    elif feat.avg_p2p_amount <= th.very_low_avg_amount_yellow:
        intensity = 0.5
    else:
        return None
    spec = RULES["very_low_avg_amount"]
    msg = (
        f"При {feat.p2p_count} P2P-операциях средний чек — {feat.avg_p2p_amount:,.0f} ₽. "
        "Десятки микро-переводов — характерный паттерн нелегального терминала или ставок."
    )
    return _make_flag(
        spec, intensity, feat.avg_p2p_amount, th.very_low_avg_amount_red, msg
    )


def _rule_atm_cashout_after_income(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.atm_cashout_after_income_ratio,
        th.atm_cashout_after_income_yellow,
        th.atm_cashout_after_income_red,
    )
    if intensity == 0:
        return None
    spec = RULES["atm_cashout_after_income"]
    msg = (
        f"В среднем {feat.atm_cashout_after_income_ratio * 100:.0f}% дохода в тот же "
        "день снимается в банкомате. МР 4-МР считает такой обнал обналичиванием в "
        "интересах третьих лиц."
    )
    return _make_flag(
        spec, intensity, feat.atm_cashout_after_income_ratio, th.atm_cashout_after_income_red, msg
    )


def _rule_one_dominant_sender(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    if feat.p2p_incoming_count < 6 and feat.incoming_unique_counterparties < 3:
        return None
    intensity = _intensity(
        feat.one_dominant_sender_share,
        th.one_dominant_sender_yellow,
        th.one_dominant_sender_red,
    )
    if intensity == 0:
        return None
    spec = RULES["one_dominant_sender"]
    msg = (
        f"{feat.one_dominant_sender_share * 100:.0f}% всех поступлений — от одного "
        "контрагента. Классический паттерн скрытой аренды или «серой» зарплаты."
    )
    return _make_flag(
        spec, intensity, feat.one_dominant_sender_share, th.one_dominant_sender_red, msg
    )


def _rule_new_card_burst(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    if feat.days_observed >= th.new_card_burst_days_max:
        return None
    intensity = _intensity(
        feat.turnover_total,
        th.new_card_burst_turnover_yellow,
        th.new_card_burst_turnover_red,
    )
    if intensity == 0:
        return None
    spec = RULES["new_card_burst"]
    msg = (
        f"Период наблюдения {feat.days_observed} дн., но оборот уже "
        f"{feat.turnover_total:,.0f} ₽. Антифрод банков (Яндекс Банк, 2026) "
        "особенно пристально смотрит на такие «молодые» счета."
    )
    return _make_flag(
        spec, intensity, feat.turnover_total, th.new_card_burst_turnover_red, msg
    )


def _rule_rejected_operations(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.rejected_operations_count,
        th.rejected_ops_count_yellow,
        th.rejected_ops_count_red,
    )
    if intensity == 0:
        return None
    spec = RULES["rejected_operations"]
    msg = (
        f"В выписке {feat.rejected_operations_count} операций с признаками отказа или "
        "возврата. Антифрод уже вас отметил — следующий шаг обычно блокировка карты."
    )
    return _make_flag(
        spec, intensity, feat.rejected_operations_count, th.rejected_ops_count_red, msg
    )


def _rule_no_card_purchases(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    if feat.tx_count < th.no_card_purchases_tx_threshold:
        return None
    if feat.card_purchases_count > 0:
        return None
    spec = RULES["no_card_purchases"]
    msg = (
        f"За {feat.days_observed} дн. и {feat.tx_count} операций — ни одной покупки по "
        "карте (магазин/такси/онлайн). По МР 16-МР п.8 счёт выглядит как дроп-счёт."
    )
    return _make_flag(spec, 1.0, 0, th.no_card_purchases_tx_threshold, msg)


# ---------- третья волна: антифрод-системы + комплаенс 2025–2026 ----------


def _rule_structuring_sub_threshold(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.structuring_sub_threshold_count,
        th.structuring_sub_threshold_yellow,
        th.structuring_sub_threshold_red,
    )
    if intensity == 0:
        return None
    spec = RULES["structuring_sub_threshold"]
    msg = (
        f"Найдено {feat.structuring_sub_threshold_count} операций прямо под порогом "
        "обязательного контроля (580–599 тыс. или 970–999 тыс. ₽). Антифрод-системы "
        "(FICO Falcon, SAS AML, ЦФТ, BSS) ловят такой паттерн как FATF-structuring."
    )
    return _make_flag(
        spec, intensity, feat.structuring_sub_threshold_count, th.structuring_sub_threshold_red, msg
    )


def _rule_smurfing_same_receiver(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    ops_intensity = _intensity(
        feat.smurfing_same_receiver_max_ops,
        th.smurfing_same_receiver_ops_yellow,
        th.smurfing_same_receiver_ops_red,
    )
    sum_intensity = _intensity(
        feat.smurfing_same_receiver_max_sum,
        th.smurfing_same_receiver_sum_yellow,
        th.smurfing_same_receiver_sum_red,
    )
    # правило срабатывает, только когда выполнены оба условия (количество + сумма)
    intensity = min(ops_intensity, sum_intensity)
    if intensity == 0:
        return None
    spec = RULES["smurfing_same_receiver"]
    msg = (
        f"Максимум {feat.smurfing_same_receiver_max_ops} переводов одному получателю за "
        f"сутки на суммарные {feat.smurfing_same_receiver_max_sum:,.0f} ₽. Классический "
        "smurfing (FATF) и обход лимита СБП 100k ₽/сутки."
    )
    return _make_flag(
        spec, intensity, feat.smurfing_same_receiver_max_ops, th.smurfing_same_receiver_ops_red, msg
    )


def _rule_nfc_atm_ops(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.nfc_atm_ops_count, th.nfc_atm_ops_yellow, th.nfc_atm_ops_red
    )
    if intensity == 0:
        return None
    spec = RULES["nfc_atm_ops"]
    msg = (
        f"В выписке {feat.nfc_atm_ops_count} операций с NFC-банкоматом. "
        "С 01.01.2026 это самостоятельный признак антифрода ЦБ РФ (ОД-2506 п.7) — "
        "схема «снятие под давлением по NFC/QR»."
    )
    return _make_flag(spec, intensity, feat.nfc_atm_ops_count, th.nfc_atm_ops_red, msg)


def _rule_droppers_registry(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.droppers_registry_hits_count,
        th.droppers_registry_hits_yellow,
        th.droppers_registry_hits_red,
    )
    if intensity == 0:
        return None
    spec = RULES["droppers_registry"]
    msg = (
        f"В выписке {feat.droppers_registry_hits_count} строк со следами реестра "
        "дропперов ФинЦЕРТ / возврата по 161-ФЗ. Банк уже остановил минимум одну "
        "операцию — следующий шаг обычно полная блокировка карты."
    )
    return _make_flag(
        spec, intensity, feat.droppers_registry_hits_count, th.droppers_registry_hits_red, msg
    )


def _rule_le_to_individual_regular(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    if feat.has_salary_anchor:
        # настоящая зарплата снимает подозрение
        return None
    intensity = _intensity(
        feat.le_to_individual_regular_count,
        th.le_to_individual_regular_yellow,
        th.le_to_individual_regular_red,
    )
    if intensity == 0:
        return None
    spec = RULES["le_to_individual_regular"]
    msg = (
        f"Найдено {feat.le_to_individual_regular_count} дней с поступлениями от ЮЛ/ИП, "
        "и это не зарплата. Обновлённое 375-П (редакция 2025) прямо относит такие "
        "переводы к подозрительным — классические «серые» выплаты или обнал через зиц-ИП."
    )
    return _make_flag(
        spec, intensity, feat.le_to_individual_regular_count, th.le_to_individual_regular_red, msg
    )


def _rule_precious_metals_after_income(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.precious_metals_after_income_count,
        th.precious_metals_after_income_yellow,
        th.precious_metals_after_income_red,
    )
    if intensity == 0:
        return None
    spec = RULES["precious_metals_after_income"]
    msg = (
        f"{feat.precious_metals_after_income_count} покупок драгметаллов в пределах 3 "
        "дней после поступления. По 375-П (ред. 2025) — прямой признак схемы "
        "«placement → integration» по FATF."
    )
    return _make_flag(
        spec,
        intensity,
        feat.precious_metals_after_income_count,
        th.precious_metals_after_income_red,
        msg,
    )


def _rule_fatf_high_risk_transfers(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.fatf_high_risk_transfers_count, th.fatf_transfers_yellow, th.fatf_transfers_red
    )
    if intensity == 0:
        return None
    spec = RULES["fatf_high_risk_transfers"]
    msg = (
        f"{feat.fatf_high_risk_transfers_count} операций с признаками юрисдикций "
        "высокого риска FATF (Иран/КНДР/офшоры/Дубай/Гонконг). Все такие операции "
        "идут через усиленный валютный и комплаенс-контроль."
    )
    return _make_flag(
        spec, intensity, feat.fatf_high_risk_transfers_count, th.fatf_transfers_red, msg
    )


def _rule_gift_loan_abuse(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    count_intensity = _intensity(
        feat.gift_loan_abuse_count, th.gift_loan_abuse_yellow, th.gift_loan_abuse_red
    )
    share_intensity = _intensity(
        feat.gift_loan_abuse_share, th.gift_loan_abuse_share_yellow, th.gift_loan_abuse_share_red
    )
    intensity = max(count_intensity, share_intensity)
    if intensity == 0:
        return None
    spec = RULES["gift_loan_abuse"]
    msg = (
        f"{feat.gift_loan_abuse_count} операций с назначением «подарок/займ/возврат "
        f"долга» ({feat.gift_loan_abuse_share * 100:.0f}% входящих P2P). МР ЦБ 4-МР "
        "называет это прямым признаком прикрытия предпринимательской активности."
    )
    return _make_flag(
        spec, intensity, feat.gift_loan_abuse_count, th.gift_loan_abuse_red, msg
    )


def _rule_velocity_per_minute(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.velocity_per_minute_max, th.velocity_per_minute_yellow, th.velocity_per_minute_red
    )
    if intensity == 0:
        return None
    spec = RULES["velocity_per_minute"]
    msg = (
        f"В один момент совершено {feat.velocity_per_minute_max} операций за минуту. "
        "FICO Falcon и ЦФТ Антифрод считают это признаком автоматизации (скрипт/бот) "
        "или перехвата сессии."
    )
    return _make_flag(
        spec, intensity, feat.velocity_per_minute_max, th.velocity_per_minute_red, msg
    )


def _rule_self_transfer_multi_banks(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.self_transfer_banks_unique,
        th.self_transfer_banks_yellow,
        th.self_transfer_banks_red,
    )
    if intensity == 0:
        return None
    spec = RULES["self_transfer_multi_banks"]
    msg = (
        f"Переводы «себе» в {feat.self_transfer_banks_unique} разных банков. "
        "Классический layering по FATF — даже если деньги ваши, банки видят "
        "попытку оторвать их от исходной точки."
    )
    return _make_flag(
        spec, intensity, feat.self_transfer_banks_unique, th.self_transfer_banks_red, msg
    )


def _rule_mirror_transfers(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.mirror_transfers_pairs_count,
        th.mirror_transfers_pairs_yellow,
        th.mirror_transfers_pairs_red,
    )
    if intensity == 0:
        return None
    spec = RULES["mirror_transfers_counterparty"]
    msg = (
        f"Найдено {feat.mirror_transfers_pairs_count} зеркальных пар P2P (туда-сюда) "
        "с одним и тем же контрагентом. По МР 4-МР это признак «прогона денег» — "
        "тест антифрода перед крупной операцией или расчёт за крипту."
    )
    return _make_flag(
        spec, intensity, feat.mirror_transfers_pairs_count, th.mirror_transfers_pairs_red, msg
    )


def _rule_sbp_split_same_receiver(feat: StatementFeatures, th: Thresholds) -> RiskFlag | None:
    intensity = _intensity(
        feat.sbp_split_same_receiver_max_ops,
        th.sbp_split_same_receiver_yellow,
        th.sbp_split_same_receiver_red,
    )
    if intensity == 0:
        return None
    spec = RULES["sbp_split_same_receiver"]
    msg = (
        f"До {feat.sbp_split_same_receiver_max_ops} СБП-переводов одному получателю "
        f"за {th.sbp_split_window_hours} ч. Классический обход лимита СБП 100k ₽/сутки — "
        "антифрод (ЦФТ/BSS) автоматически помечает такой канал."
    )
    return _make_flag(
        spec, intensity, feat.sbp_split_same_receiver_max_ops, th.sbp_split_same_receiver_red, msg
    )


_RULE_FUNCS = [
    _rule_p2p_daily,
    _rule_p2p_month,
    _rule_p2p_counterparties,
    _rule_transit,
    _rule_large_income,
    _rule_monthly_turnover,
    _rule_micro_tx,
    _rule_hidden_business,
    _rule_crypto,
    _rule_cash,
    _rule_spike,
    _rule_161,
    _rule_gambling,
    # правила из banki.ru-кейсов 2025–2026
    _rule_fast_in_out,
    _rule_no_lifestyle,
    _rule_round_the_clock,
    _rule_crypto_gambling_combo,
    _rule_sbp_out_after_income,
    _rule_third_party_cash,
    _rule_ip_samozanyat,
    _rule_collective_fundraising,
    _rule_new_senders_dominance,
    # вторая волна
    _rule_round_amounts_pattern,
    _rule_identical_amount_repeats,
    _rule_salary_day_drain,
    _rule_dormant_then_active,
    _rule_multi_bank_fanout,
    _rule_cross_border_transfers,
    _rule_very_low_avg_amount,
    _rule_atm_cashout_after_income,
    _rule_one_dominant_sender,
    _rule_new_card_burst,
    _rule_rejected_operations,
    _rule_no_card_purchases,
    # третья волна — антифрод-системы и комплаенс 2025–2026
    _rule_structuring_sub_threshold,
    _rule_smurfing_same_receiver,
    _rule_nfc_atm_ops,
    _rule_droppers_registry,
    _rule_le_to_individual_regular,
    _rule_precious_metals_after_income,
    _rule_fatf_high_risk_transfers,
    _rule_gift_loan_abuse,
    _rule_velocity_per_minute,
    _rule_self_transfer_multi_banks,
    _rule_mirror_transfers,
    _rule_sbp_split_same_receiver,
]


# ----------------------------- финальный скоринг -----------------------


def _rule_total_weight() -> float:
    """Сумма весов всех правил при максимальном срабатывании.

    Нужна, чтобы привести rule_score к [0..100].
    """
    return sum(spec.weight for spec in RULES.values())


def _level_from_score(score: float) -> RiskLevel:
    if score >= 65:
        return RiskLevel.RED
    if score >= 30:
        return RiskLevel.YELLOW
    return RiskLevel.GREEN


def _build_summary(score: float, level: RiskLevel, flags: list[RiskFlag]) -> str:
    if not flags:
        return (
            "По вашей выписке ярких признаков 115-ФЗ не найдено. "
            "Продолжайте вести счёт прозрачно — и всё будет хорошо."
        )
    red = [f for f in flags if f.severity == "red"]
    yellow = [f for f in flags if f.severity == "yellow"]
    if level == RiskLevel.RED:
        lead = (
            "Внимание: по нескольким ключевым признакам ваша выписка похожа на те, "
            "которые банки в 2025–2026 блокировали по 115-ФЗ."
        )
    elif level == RiskLevel.YELLOW:
        lead = "Есть пограничные моменты — их можно починить до того, как банк задаст вопросы."
    else:
        lead = "Ниже — мягкие замечания, по которым всё же стоит подкорректировать поведение."
    return f"{lead} Оценка риска: {score:.0f}/100. Красных флагов: {len(red)}, жёлтых: {len(yellow)}."


def _build_recommendations(flags: list[RiskFlag]) -> list[str]:
    """Собрать план действий: уникальные, упорядоченные по весу."""
    seen: set[str] = set()
    recs: list[tuple[float, str]] = []
    for f in sorted(flags, key=lambda x: x.contribution, reverse=True):
        hint = f.action_hint.strip()
        if hint and hint not in seen:
            seen.add(hint)
            recs.append((f.contribution, hint))
    # добавляем универсальные советы в хвост
    universal = [
        "Не принимайте чужие переводы «для знакомого / за комиссию» — это самый быстрый путь под 115-ФЗ.",
        "Храните договоры/расписки по всем крупным операциям минимум 3 года.",
        "Если банк попросил документы — отвечайте в срок и спокойно, это штатная процедура.",
    ]
    for u in universal:
        if u not in seen:
            recs.append((0.0, u))
    return [r[1] for r in recs]


def assess_risk(
    features: StatementFeatures,
    *,
    thresholds: Thresholds | None = None,
    ml_probability: float | None = None,
    ml_alpha: float = 0.4,
) -> RiskAssessment:
    """Сформировать :class:`RiskAssessment` по признакам выписки.

    Args:
        features: признаки выписки, см. :func:`feature_engineering.compute_features`.
        thresholds: пороги правил; по умолчанию :data:`DEFAULT_THRESHOLDS`.
        ml_probability: опциональная вероятность от ML-модели (0..1).
        ml_alpha: вес ML в финальной вероятности (0..1).  При ``None``
            используется только rule-based скоринг.
    """
    th = thresholds or DEFAULT_THRESHOLDS
    flags: list[RiskFlag] = []
    for fn in _RULE_FUNCS:
        flag = fn(features, th)
        if flag is not None:
            flags.append(flag)

    raw_weight = sum(f.contribution for f in flags)
    rule_score = 100.0 * raw_weight / _rule_total_weight()
    # сдвиг+наклон подобран так, чтобы при срабатывании ~40% правил получить 0.5.
    rule_prob = _sigmoid((rule_score - 45.0) / 12.0)

    if ml_probability is None:
        probability = rule_prob
    else:
        ml_alpha = max(0.0, min(1.0, ml_alpha))
        probability = ml_alpha * ml_probability + (1 - ml_alpha) * rule_prob

    # Композитный score: 60% rule-score + 40% sigmoid * 100 — чтобы шкала
    # совпадала с человеческим восприятием «как сильно горит красным».
    score = min(100.0, 0.6 * rule_score + 0.4 * probability * 100.0)
    level = _level_from_score(score)
    summary = _build_summary(score, level, flags)
    recs = _build_recommendations(flags)

    return RiskAssessment(
        risk_score=float(score),
        probability=float(probability),
        level=level,
        flags=sorted(flags, key=lambda f: f.contribution, reverse=True),
        ml_probability=ml_probability,
        rule_score=float(rule_score),
        recommendations=recs,
        summary=summary,
    )


# ----------------------------- what-if ---------------------------------


def whatif_adjust_features(
    base: StatementFeatures,
    *,
    add_p2p_30d: int = 0,
    add_large_income: float = 0.0,
    add_cash_share: float = 0.0,
    add_crypto_ops: int = 0,
) -> StatementFeatures:
    """Вернуть копию ``StatementFeatures`` с применёнными «что-если» правками.

    Используется для симулятора в UI: пользователь двигает ползунки, мы
    пересчитываем ``RiskAssessment`` без повторного парсинга выписки.
    """
    import dataclasses

    new = dataclasses.replace(base)
    new.p2p_last30d = max(0, new.p2p_last30d + add_p2p_30d)
    new.p2p_count = max(0, new.p2p_count + add_p2p_30d)
    new.p2p_max_per_day = max(new.p2p_max_per_day, int(add_p2p_30d // 7 + 1) if add_p2p_30d > 0 else new.p2p_max_per_day)
    if add_large_income > 0:
        new.largest_income = max(new.largest_income, add_large_income)
        new.income_total = new.income_total + add_large_income
        new.large_income_count = new.large_income_count + 1
        new.turnover_total = new.turnover_total + add_large_income
        new.monthly_turnover = new.monthly_turnover + add_large_income * (30.0 / max(1, new.days_observed))
    if add_cash_share > 0:
        new.cash_ratio = min(1.0, new.cash_ratio + add_cash_share)
    if add_crypto_ops > 0:
        new.crypto_ops_count = new.crypto_ops_count + add_crypto_ops
    return new
