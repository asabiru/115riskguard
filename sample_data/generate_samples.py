"""Генератор демо-выписок для разных банков.

Скрипт создаёт пять файлов в папке ``sample_data/``, по одному на банк,
с различными профилями риска (от «зелёного» до «красного»), чтобы можно
было сразу прогнать пайплайн без настоящей выписки.

Запуск::

    python sample_data/generate_samples.py

Файлы:
    * ``sber_sample.csv``      — зелёный профиль (зарплата + покупки).
    * ``tinkoff_sample.csv``   — жёлтый (много P2P, самозанятый).
    * ``alfa_sample.csv``      — красный (скрытый бизнес + мелкие P2P).
    * ``vtb_sample.xlsx``      — жёлтый (крупное поступление без документов).
    * ``gazprom_sample.xlsx``  — красный (транзит + крипта).
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).resolve().parent
RNG = random.Random(42)


# -------------------- utilities --------------------


def _rand_time(base: datetime) -> datetime:
    return base.replace(hour=RNG.randint(7, 23), minute=RNG.randint(0, 59), second=RNG.randint(0, 59))


def _fmt_rub(value: float) -> str:
    # рублёвый формат с запятой как разделителем дробной
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


# -------------------- Сбер: "зелёный" профиль --------------------


def make_sber() -> Path:
    start = datetime(2026, 1, 1)
    rows = []
    for d in range(60):
        day = start + timedelta(days=d)
        if d % 15 == 0:  # аванс / зарплата
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Сумма операции": _fmt_rub(65_000),
                    "Валюта операции": "RUB",
                    "Описание": "Зарплата от ООО 'Ромашка'",
                    "Категория": "Зарплата",
                }
            )
        # пара-тройка покупок в день
        for _ in range(RNG.randint(2, 4)):
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Сумма операции": _fmt_rub(-RNG.randint(200, 3500)),
                    "Валюта операции": "RUB",
                    "Описание": RNG.choice(
                        [
                            "Покупка Магнит",
                            "Покупка Пятёрочка",
                            "Оплата Яндекс.Еда",
                            "Покупка OZON",
                            "АЗС Лукойл",
                            "Кофейня Cofix",
                        ]
                    ),
                    "Категория": "Покупки",
                }
            )
        if RNG.random() < 0.08:
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Сумма операции": _fmt_rub(-5000),
                    "Валюта операции": "RUB",
                    "Описание": "Перевод СБП другу",
                    "Категория": "P2P переводы",
                }
            )
    df = pd.DataFrame(rows)
    path = OUT_DIR / "sber_sample.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


# -------------------- Тинькофф: "жёлтый" --------------------


def make_tinkoff() -> Path:
    start = datetime(2026, 2, 1)
    rows = []
    for d in range(30):
        day = start + timedelta(days=d)
        # 10-14 P2P в день (много, но не критично)
        for _ in range(RNG.randint(8, 14)):
            amount = RNG.choice([-500, -1000, -1500, 2500, 3200, -7000])
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Дата платежа": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Сумма операции": _fmt_rub(amount),
                    "Валюта операции": "RUB",
                    "Сумма платежа": _fmt_rub(amount),
                    "Валюта платежа": "RUB",
                    "Кэшбэк": "0,00",
                    "Категория": "Переводы",
                    "MCC": "4829",
                    "Описание": "Перевод СБП по номеру телефона",
                    "Бонусы (включая кэшбэк)": 0,
                    "Округление на инвесткопилку": 0,
                    "Сумма операции с округлением": _fmt_rub(amount),
                }
            )
        if RNG.random() < 0.2:
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Дата платежа": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Сумма операции": _fmt_rub(-2000),
                    "Валюта операции": "RUB",
                    "Сумма платежа": _fmt_rub(-2000),
                    "Валюта платежа": "RUB",
                    "Кэшбэк": "0,00",
                    "Категория": "Супермаркеты",
                    "MCC": "5411",
                    "Описание": "Покупка Магнит",
                    "Бонусы (включая кэшбэк)": 0,
                    "Округление на инвесткопилку": 0,
                    "Сумма операции с округлением": _fmt_rub(-2000),
                }
            )
    df = pd.DataFrame(rows)
    path = OUT_DIR / "tinkoff_sample.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig", sep=";")
    return path


# -------------------- Альфа: "красный" (скрытый бизнес + микро-P2P) --------


def make_alfa() -> Path:
    start = datetime(2026, 2, 15)
    rows = []
    counter = 0
    for d in range(20):
        day = start + timedelta(days=d)
        # десятки мелких входящих "за услугу"
        for _ in range(RNG.randint(25, 55)):
            counter += 1
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Референс": f"REF{counter:06d}",
                    "Описание операции": RNG.choice(
                        [
                            "Перевод клиенту от Иванов И.И. за услугу",
                            "Перевод СБП от Петров П.П. оплата товара",
                            "Перевод СБП от Сидоров С.С. за работу",
                            "Перевод СБП от Кузнецов К.К. по договору",
                        ]
                    ),
                    "Сумма в валюте счёта": _fmt_rub(RNG.choice([1500, 1800, 2500, 3500, 5000])),
                    "Валюта счёта": "RUB",
                }
            )
        # исходящие расходы "на жизнь"
        for _ in range(RNG.randint(2, 4)):
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Референс": f"REF{counter:06d}O",
                    "Описание операции": RNG.choice(["Покупка Перекрёсток", "Покупка Wildberries", "АЗС"]),
                    "Сумма в валюте счёта": _fmt_rub(-RNG.randint(500, 4000)),
                    "Валюта счёта": "RUB",
                }
            )
    df = pd.DataFrame(rows)
    path = OUT_DIR / "alfa_sample.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


# -------------------- ВТБ: "жёлтый" (крупное поступление) --------


def make_vtb() -> Path:
    start = datetime(2026, 3, 1)
    rows = []
    for d in range(45):
        day = start + timedelta(days=d)
        if d == 15:
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Дата обработки": _rand_time(day).strftime("%d.%m.%Y"),
                    "Операция": "Входящий перевод",
                    "Сумма в руб": _fmt_rub(850_000),
                }
            )
        if d % 14 == 0:
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Дата обработки": _rand_time(day).strftime("%d.%m.%Y"),
                    "Операция": "Зачисление заработной платы",
                    "Сумма в руб": _fmt_rub(80_000),
                }
            )
        for _ in range(RNG.randint(2, 5)):
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Дата обработки": _rand_time(day).strftime("%d.%m.%Y"),
                    "Операция": RNG.choice(["Покупка Ашан", "Оплата ЖКХ", "Покупка Citilink", "СБП другу"]),
                    "Сумма в руб": _fmt_rub(-RNG.randint(300, 9000)),
                }
            )
    df = pd.DataFrame(rows)
    path = OUT_DIR / "vtb_sample.xlsx"
    df.to_excel(path, index=False)
    return path


# -------------------- Газпром: "красный" (транзит + крипта) --------


def make_gazprom() -> Path:
    start = datetime(2026, 3, 5)
    rows = []
    for d in range(25):
        day = start + timedelta(days=d)
        # крупное поступление
        rows.append(
            {
                "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                "Описание": "Входящий перевод СБП от Петрова А.А.",
                "Приход": _fmt_rub(RNG.randint(120_000, 300_000)),
                "Расход": _fmt_rub(0),
            }
        )
        # выводы
        for _ in range(RNG.randint(2, 5)):
            rows.append(
                {
                    "Дата операции": _rand_time(day).strftime("%d.%m.%Y %H:%M:%S"),
                    "Описание": RNG.choice(
                        [
                            "Перевод СБП Bybit обменник",
                            "Перевод физлицу Garantex P2P",
                            "Снятие наличных банкомат",
                            "Перевод СБП по номеру телефона",
                        ]
                    ),
                    "Приход": _fmt_rub(0),
                    "Расход": _fmt_rub(RNG.randint(40_000, 95_000)),
                }
            )
    df = pd.DataFrame(rows)
    path = OUT_DIR / "gazprom_sample.xlsx"
    df.to_excel(path, index=False)
    return path


# -------------------- main --------------------


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    created = [fn() for fn in (make_sber, make_tinkoff, make_alfa, make_vtb, make_gazprom)]
    for path in created:
        print(f"created: {path.relative_to(OUT_DIR.parent)}")


if __name__ == "__main__":
    main()
