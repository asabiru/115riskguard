"""Тесты мультибанковского парсера."""

from __future__ import annotations

import pandas as pd
import pytest

from riskguard.parser import (
    _parse_sber_pdf_text,
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


class TestSberPdfTextParser:
    """Регрессия: PDF-выписка Сбера 2026 не должна уходить в «Универсальный»,
    и 6-значные коды авторизации не должны попадать в сумму."""

    SAMPLE = """900 www.sberbank.ru Заказано в СберБанк Онлайн
Выписка по платёжному счёту
ИТОГО ПО ОПЕРАЦИЯМ ЗА ПЕРИОД:
Остаток на 25.03.2026 0,00
Номер счёта 40817 810 6 5410 2820880 Пополнение 58 320,00
Валюта Российский рубль Списание 57 857,16
Остаток на 24.04.2026 462,84
Расшифровка операций
13.04.2026 02:19 Перевод с карты 3 084,00 462,84
13.04.2026 513734 Перевод для В. Даниил Эдуардович. Операция по счету
****0880
11.04.2026 01:37 Перевод на карту +300,00 4 471,84
11.04.2026 168383 Перевод от Р. Кирилл Сергеевич. Операция по счету
****0880
06.04.2026 19:11 Прочие операции +42 000,00 42 693,85
06.04.2026 140280 Прочие выплаты. Операция по счету ****0880
"""

    def test_parses_three_ops_with_correct_signs(self):
        df = _parse_sber_pdf_text(self.SAMPLE)
        assert len(df) == 3
        assert df["Сумма"].tolist() == [-3084.0, 300.0, 42000.0]
        # Коды авторизации не должны попадать в сумму.
        assert 513734 not in df["Сумма"].tolist()
        assert 168383 not in df["Сумма"].tolist()

    def test_totals_match_statement_summary(self):
        df = _parse_sber_pdf_text(self.SAMPLE)
        income = df.loc[df["Сумма"] > 0, "Сумма"].sum()
        expense = df.loc[df["Сумма"] < 0, "Сумма"].sum()
        assert income == 42300.0  # 300 + 42 000
        assert expense == -3084.0

    def test_detect_bank_recognises_sber(self):
        df = _parse_sber_pdf_text(self.SAMPLE)
        assert detect_bank(df) == "Сбер"


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
