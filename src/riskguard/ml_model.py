"""Опциональная ML-модель (CatBoost) поверх rule-based движка.

Реальные помеченные данные о блокировках 115-ФЗ — чувствительная вещь,
поэтому в репозитории поставляется только каркас:

* :class:`RiskMLModel` — тонкая обёртка над CatBoostClassifier с
  возможностью дообучения (``fit``/``save``/``load``).
* :func:`features_to_vector` — устойчивое преобразование
  :class:`StatementFeatures` в числовой вектор с фиксированным порядком
  признаков (важно для совместимости сохранённой модели).
* :func:`synthetic_training_dataset` — генератор синтетических данных,
  который пользователь может использовать как стартовый пример.

Если модель не загружена, весь пайплайн остаётся работоспособным —
rule-based движок считает итоговый риск самостоятельно.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .feature_engineering import StatementFeatures

logger = logging.getLogger(__name__)


# Фиксированный порядок признаков: менять только добавлением в конец.
FEATURE_ORDER: tuple[str, ...] = (
    "days_observed",
    "tx_count",
    "income_total",
    "expense_total",
    "net_flow",
    "turnover_total",
    "monthly_turnover",
    "p2p_count",
    "p2p_incoming_count",
    "p2p_outgoing_count",
    "p2p_unique_counterparties",
    "p2p_max_per_day",
    "p2p_last7d",
    "p2p_last30d",
    "same_day_turnover_share",
    "residual_ratio",
    "transit_days_count",
    "small_tx_count",
    "small_tx_per_day_max",
    "large_income_count",
    "largest_income",
    "cash_volume",
    "cash_ratio",
    "crypto_ops_count",
    "gambling_ops_count",
    "incoming_unique_counterparties",
    "incoming_from_individuals_count",
    "business_like_score",
    "turnover_spike_ratio",
    "max_daily_turnover",
    "new_counterparty_share",
    "night_tx_ratio",
    "has_salary_anchor",
    # --- добавлено после разбора banki.ru-кейсов 2025–2026 ---
    "fast_inout_share",
    "fast_inout_pairs_count",
    "has_lifestyle_payments",
    "lifestyle_payments_count",
    "days_without_lifestyle",
    "active_hours_span",
    "active_hours_avg_per_day",
    "sbp_out_after_income_share",
    "third_party_cash_deposits_count",
    "ip_samozanyat_transfers_count",
    "collective_fundraising_max_unique",
    "new_senders_share",
    # --- вторая волна: разбор 100+ кейсов banki.ru 2025–2026 ---
    "round_amounts_share",
    "identical_amount_max_repeats",
    "salary_day_drain_ratio",
    "dormant_days_before_spike",
    "multi_bank_fanout_max",
    "cross_border_transfers_count",
    "avg_p2p_amount",
    "atm_cashout_after_income_ratio",
    "one_dominant_sender_share",
    "rejected_operations_count",
    "card_purchases_count",
)


def features_to_vector(feat: StatementFeatures) -> np.ndarray:
    """Преобразовать :class:`StatementFeatures` в вектор ``float`` в FEATURE_ORDER."""
    d = asdict(feat)
    return np.array([float(bool(d[k])) if isinstance(d[k], bool) else float(d[k] or 0.0) for k in FEATURE_ORDER])


class RiskMLModel:
    """Обёртка над CatBoostClassifier с lazy-импортом.

    Если catboost не установлен или модель не обучена — ``predict_proba``
    возвращает ``None`` и пайплайн откатывается на rule-based оценку.
    """

    def __init__(self) -> None:
        self._clf = None  # type: ignore[var-annotated]

    @property
    def is_ready(self) -> bool:
        return self._clf is not None

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        *,
        iterations: int = 400,
        depth: int = 6,
        learning_rate: float = 0.05,
    ) -> None:
        """Обучить модель на матрице признаков и бинарной метке блокировки."""
        from catboost import CatBoostClassifier  # локальный импорт

        self._clf = CatBoostClassifier(
            iterations=iterations,
            depth=depth,
            learning_rate=learning_rate,
            loss_function="Logloss",
            eval_metric="AUC",
            verbose=False,
            random_seed=42,
        )
        self._clf.fit(X, y)

    def predict_proba(self, feat: StatementFeatures) -> float | None:
        """Вернуть вероятность блокировки [0..1] или ``None``, если модель не готова."""
        if self._clf is None:
            return None
        vec = features_to_vector(feat).reshape(1, -1)
        try:
            proba = float(self._clf.predict_proba(vec)[0, 1])
        except Exception as exc:  # noqa: BLE001
            logger.warning("ML predict_proba failed: %s", exc)
            return None
        return proba

    # -------------------- сохранение / загрузка ---------------------

    def save(self, path: str | Path) -> None:
        if self._clf is None:
            raise RuntimeError("Нечего сохранять: модель не обучена.")
        self._clf.save_model(str(path))

    def load(self, path: str | Path) -> None:
        from catboost import CatBoostClassifier

        clf = CatBoostClassifier()
        clf.load_model(str(path))
        self._clf = clf


# --------------------------- synthetic data ----------------------------


def synthetic_training_dataset(
    n_clean: int = 400, n_risk: int = 400, seed: int = 7
) -> tuple[np.ndarray, np.ndarray]:
    """Сгенерировать стартовый синтетический датасет для первого обучения.

    «Риск» = 1, если выписка похожа на кейсы из banki.ru: много P2P,
    транзит, крипта, скрытый бизнес.  «Чистые» = 0: зарплата + покупки.

    Важно: это *демонстрационные* данные.  На проде стоит подменить их
    реальной размеченной историей.
    """
    rng = np.random.default_rng(seed)

    def _clean() -> StatementFeatures:
        f = StatementFeatures()
        f.days_observed = int(rng.integers(30, 90))
        f.tx_count = int(rng.integers(40, 200))
        f.income_total = float(rng.normal(90_000, 20_000))
        f.expense_total = f.income_total * rng.uniform(0.7, 0.95)
        f.net_flow = f.income_total - f.expense_total
        f.turnover_total = f.income_total + f.expense_total
        f.monthly_turnover = f.turnover_total * (30 / f.days_observed)
        f.p2p_count = int(rng.integers(0, 10))
        f.p2p_last30d = int(min(f.p2p_count, rng.integers(0, 8)))
        f.p2p_unique_counterparties = int(rng.integers(0, 6))
        f.p2p_max_per_day = int(rng.integers(0, 3))
        f.same_day_turnover_share = float(rng.uniform(0.0, 0.2))
        f.residual_ratio = float(rng.uniform(0.1, 0.6))
        f.cash_ratio = float(rng.uniform(0.0, 0.15))
        f.has_salary_anchor = True
        return f

    def _risk() -> StatementFeatures:
        f = StatementFeatures()
        f.days_observed = int(rng.integers(20, 60))
        f.tx_count = int(rng.integers(200, 600))
        f.income_total = float(rng.uniform(400_000, 1_500_000))
        f.expense_total = f.income_total * rng.uniform(0.9, 1.0)
        f.net_flow = f.income_total - f.expense_total
        f.turnover_total = f.income_total + f.expense_total
        f.monthly_turnover = f.turnover_total * (30 / f.days_observed)
        f.p2p_count = int(rng.integers(80, 400))
        f.p2p_last30d = int(rng.integers(60, 300))
        f.p2p_unique_counterparties = int(rng.integers(40, 120))
        f.p2p_max_per_day = int(rng.integers(15, 60))
        f.same_day_turnover_share = float(rng.uniform(0.7, 0.98))
        f.residual_ratio = float(rng.uniform(0.0, 0.1))
        f.cash_ratio = float(rng.uniform(0.2, 0.7))
        f.crypto_ops_count = int(rng.integers(0, 20))
        f.incoming_unique_counterparties = int(rng.integers(30, 100))
        f.incoming_from_individuals_count = int(rng.integers(10, 80))
        f.turnover_spike_ratio = float(rng.uniform(2.5, 10.0))
        f.new_counterparty_share = float(rng.uniform(0.4, 0.95))
        f.night_tx_ratio = float(rng.uniform(0.1, 0.4))
        f.has_salary_anchor = bool(rng.integers(0, 2))
        return f

    samples = [_clean() for _ in range(n_clean)] + [_risk() for _ in range(n_risk)]
    labels = [0] * n_clean + [1] * n_risk
    X = np.vstack([features_to_vector(s) for s in samples])
    y = np.array(labels, dtype=np.int32)
    return X, y
