"""Тесты фичей выписки."""

from __future__ import annotations

import pandas as pd

from riskguard.constants import CANONICAL_COLUMNS
from riskguard.feature_engineering import compute_features


def _build_df(rows):
    return pd.DataFrame(rows, columns=list(CANONICAL_COLUMNS))


def test_empty_df_returns_zeros():
    feat = compute_features(_build_df([]))
    assert feat.tx_count == 0
    assert feat.p2p_count == 0
    assert feat.residual_ratio == 1.0


def test_basic_aggregates():
    rows = [
        [pd.Timestamp("2026-02-01"), 100_000, "RUB", "Зарплата", "ООО", "Зарплата", None, "income", "other", None],
        [pd.Timestamp("2026-02-02"), -3_000, "RUB", "Покупка Магнит", "Магнит", "Покупки", None, "expense", "card", None],
        [pd.Timestamp("2026-02-03"), -20_000, "RUB", "Перевод СБП", "Иванов", "P2P", None, "expense", "p2p", None],
    ]
    feat = compute_features(_build_df(rows))
    assert feat.tx_count == 3
    assert feat.income_total == 100_000
    assert feat.expense_total == 23_000
    assert feat.p2p_count == 1
    assert feat.has_salary_anchor is True


def test_p2p_spike_detection():
    rows = []
    for i in range(25):
        rows.append(
            [
                pd.Timestamp("2026-02-05") + pd.Timedelta(minutes=20 * i),
                -1500,
                "RUB",
                f"Перевод СБП физлицу #{i}",
                f"cp{i}",
                "P2P",
                None,
                "expense",
                "p2p",
                None,
            ]
        )
    feat = compute_features(_build_df(rows))
    assert feat.p2p_max_per_day >= 25
    assert feat.p2p_unique_counterparties >= 20
