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
