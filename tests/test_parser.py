"""Тесты мультибанковского парсера."""

from __future__ import annotations

import pandas as pd
import pytest

from riskguard.parser import (
    _to_float,
    detect_bank,
    infer_channel,
    normalize_dataframe,
    parse_statement,
)


class TestToFloat:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1 234,56", 1234.56),
            ("1,234.56", 1234.56),
            ("-500,00 ₽", -500.0),
            ("(500,00)", -500.0),
            ("0", 0.0),
            ("", None),
            (None, None),
        ],
    )
    def test_robust_parsing(self, raw, expected):
        assert _to_float(raw) == expected


class TestInferChannelMerchantVsP2P:
    """QR-оплата мерчанту не должна считаться P2P-переводом."""

    def test_sbp_qr_merchant_is_card_not_p2p(self):
        from riskguard.parser import infer_channel

        # «Оплата по QR–коду СБП» — это оплата мерчанту, НЕ P2P.
        assert infer_channel("FUNPAY. Операция по карте ****2546", "Оплата по QR–коду СБП") == "card"
        assert (
            infer_channel("1shot.club. Операция по карте ****2546", "Оплата по QR–коду СБП")
            == "card"
        )
        assert (
            infer_channel("QSR 25101_P_QR SAMARA RUS. Операция по карте ****2546", "Оплата по QR–коду СБП")
            == "card"
        )

    def test_merchant_category_is_card(self):
        from riskguard.parser import infer_channel

        assert (
            infer_channel("Додо Пицца, Самара-11. Операция по карте ****2546", "Рестораны и кафе")
            == "card"
        )
        assert (
            infer_channel(
                "PYATEROCHKA 6774_P_QR SAMARA RUS. Операция по карте ****2546", "Супермаркеты"
            )
            == "card"
        )

    def test_p2p_person_transfer_stays_p2p(self):
        from riskguard.parser import infer_channel

        assert (
            infer_channel(
                "Перевод для К. Гордей Алексеевич. Операция по счету ****0880", "Перевод с карты"
            )
            == "p2p"
        )
        assert (
            infer_channel(
                "Перевод от К. Даниил Алексеевич. Операция по счету ****0880", "Перевод на карту"
            )
            == "p2p"
        )


class TestInferChannel:
    @pytest.mark.parametrize(
        "description, expected",
        [
            ("Перевод СБП по номеру телефона", "p2p"),
            ("Снятие наличных в банкомате", "cash"),
            ("Покупка Bybit P2P обменник", "crypto"),
            ("Ставка Fonbet", "gambling"),
            ("Покупка Магнит", "card"),
            ("Подписка YouTube Premium", "online"),
        ],
    )
    def test_keywords(self, description, expected):
        assert infer_channel(description) == expected


class TestDetectBank:
    def test_sber(self):
        df = pd.DataFrame({"Дата операции": [], "Сумма операции": [], "Категория": []})
        assert detect_bank(df) in {"Сбер", "Тинькофф"}

    def test_tinkoff(self):
        df = pd.DataFrame(
            {
                "Дата операции": [],
                "Дата платежа": [],
                "Сумма операции": [],
                "Валюта операции": [],
                "MCC": [],
            }
        )
        assert detect_bank(df) == "Тинькофф"

    def test_unknown_fallback(self):
        df = pd.DataFrame({"foo": [], "bar": []})
        assert detect_bank(df) == "Универсальный"


class TestNormalize:
    def test_minimal_canonicalization(self):
        df = pd.DataFrame(
            {
                "Дата": ["01.02.2026", "02.02.2026"],
                "Сумма": ["1 000,00", "-500,00"],
                "Описание": ["Зарплата", "Покупка"],
            }
        )
        out, warnings = normalize_dataframe(df)
        assert list(out.columns)[:2] == ["date", "amount"]
        assert out["amount"].tolist() == [1000.0, -500.0]
        assert warnings == []

    def test_credit_debit_split(self):
        df = pd.DataFrame(
            {
                "Дата операции": ["01.02.2026"],
                "Описание": ["Поступление"],
                "Приход": ["50 000,00"],
                "Расход": ["0,00"],
            }
        )
        out, _ = normalize_dataframe(df)
        assert out["amount"].iloc[0] == 50_000.0

    def test_missing_amount_raises(self):
        df = pd.DataFrame({"Дата": ["01.02.2026"]})
        with pytest.raises(ValueError):
            normalize_dataframe(df)


class TestParseStatement:
    def test_csv_roundtrip(self, tmp_path):
        df = pd.DataFrame(
            {
                "Дата операции": ["01.02.2026", "02.02.2026"],
                "Сумма операции": ["1 000,00", "-500,00"],
                "Описание": ["Зарплата", "Покупка Магнит"],
            }
        )
        csv_path = tmp_path / "demo.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        out, info = parse_statement(csv_path)
        assert len(out) == 2
        assert info.rows_parsed == 2
        assert info.bank in {"Сбер", "Универсальный", "Тинькофф"}
