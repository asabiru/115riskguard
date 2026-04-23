"""Тесты фичей выписки."""

from __future__ import annotations

import pandas as pd

from riskguard.constants import CANONICAL_COLUMNS
from riskguard.feature_engineering import _extract_counterparty, compute_features


class TestExtractCounterparty:
    """Варианты записи одного человека должны сворачиваться в один ключ,
    а мерчант-операции — давать пустой ключ (не считаться контрагентом)."""

    def test_same_person_with_different_tails_is_single_key(self):
        variants = [
            "Перевод от К. Гордей Алексеевич. Операция по счету ****0880",
            "Перевод для К. Гордей Алексеевич. Операция по счету ****0880",
            "Перевод от К. Гордей Алексеевич. Операция по карте ****2546",
            "Перевод для К. Гордей Алексеевич. Операция по карте ****2546 * *",
        ]
        keys = {_extract_counterparty(v, "") for v in variants}
        assert keys == {"к. гордей алексеевич"}

    def test_merchant_descriptions_return_empty_key(self):
        # мерчант-операции не должны увеличивать счётчик контрагентов
        merchants = [
            "Додо Пицца, Самара-11. Операция по карте ****2546",
            "FUNPAY. Операция по карте ****2546",
            "PYATEROCHKA 6774_P_QR SAMARA RUS. Операция по",
            "1shot.club. Операция по карте ****2546",
            "QSR 25101_P_QR SAMARA RUS. Операция по карте ****2546",
        ]
        keys = {_extract_counterparty(m, "") for m in merchants}
        assert keys == {""}

    def test_explicit_counterparty_column_overrides(self):
        # Нормализатор сворачивает висячие точки/дефисы.
        assert (
            _extract_counterparty("Перевод для К. Гордей Алексеевич", "Петров И. И.")
            == "петров и. и"
        )


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
