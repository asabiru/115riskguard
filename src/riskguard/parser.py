"""Мультибанковский парсер выписок.

Поддерживает CSV/Excel выписки Сбербанка, Тинькофф, Альфа-Банка, ВТБ,
Газпромбанка и произвольный универсальный формат; для PDF используется
``pdfplumber``.  Все форматы приводятся к единой канонической схеме,
определённой в :mod:`riskguard.constants`.

Дизайн парсера построен на двух идеях:

1. **Карты синонимов.**  Для каждого канонического поля задан набор
   русских и английских названий колонок, которые этим полем
   являются у разных банков.  Этого достаточно, чтобы корректно
   распознавать как экспорт «родным» форматом банка, так и любые
   выписки, приведённые пользователем к таблице вручную.

2. **Ранжирование по уверенности.**  Парсер сначала пробует узнать
   банк по заголовку/имени файла, а затем проверяет, что найденный
   маппинг действительно покрывает обязательные поля (дата + сумма).
   Если совпадений нет — используется универсальный алгоритм.

Публичный API:
    * :func:`parse_statement` — принимает путь/буфер и возвращает
      ``(DataFrame, ParseInfo)``.  Это основная точка входа для UI.
    * :func:`detect_bank` — опознать банк по DataFrame.
    * :func:`normalize_dataframe` — привести произвольный DataFrame к
      каноническим колонкам.
"""

from __future__ import annotations

import io
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .constants import (
    CANON_AMOUNT,
    CANON_BALANCE,
    CANON_CATEGORY,
    CANON_CHANNEL,
    CANON_COUNTERPARTY,
    CANON_CURRENCY,
    CANON_DATE,
    CANON_DESCRIPTION,
    CANON_MCC,
    CANON_TYPE,
    CANONICAL_COLUMNS,
    CASH_KEYWORDS,
    CRYPTO_KEYWORDS,
    GAMBLING_KEYWORDS,
    P2P_KEYWORDS,
)

logger = logging.getLogger(__name__)

# ----------------------------- типы ------------------------------------


@dataclass
class ParseInfo:
    """Мета-информация о результате парсинга выписки."""

    bank: str
    rows_total: int
    rows_parsed: int
    date_min: pd.Timestamp | None
    date_max: pd.Timestamp | None
    currency: str = "RUB"
    warnings: list[str] = field(default_factory=list)

    @property
    def date_range_days(self) -> int:
        if self.date_min is None or self.date_max is None:
            return 0
        return max(1, int((self.date_max - self.date_min).days) + 1)


# ----------------------------- карты синонимов --------------------------

# Синонимы канонических колонок.  Строки сравниваются case-insensitive,
# с удалением не-буквенных символов, чтобы пережить пробелы/кавычки/№.
COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    CANON_DATE: (
        "дата",
        "датаоперации",
        "датаплатежа",
        "датаавторизации",
        "датапроведения",
        "датасписания",
        "datetime",
        "date",
        "operationdate",
        "transactiondate",
    ),
    CANON_AMOUNT: (
        "сумма",
        "суммаоперации",
        "суммавалютеоперации",
        "суммавалютесчета",
        "суммавалютесчёта",
        "суммапоплатежу",
        "суммаврублях",
        "суммавруб",
        "amount",
        "operationamount",
        "transactionamount",
    ),
    CANON_CURRENCY: (
        "валюта",
        "валютаоперации",
        "валютасчета",
        "валютасчёта",
        "currency",
    ),
    CANON_DESCRIPTION: (
        "описание",
        "описаниеоперации",
        "назначениеплатежа",
        "назначение",
        "детализация",
        "комментарий",
        "description",
        "purpose",
        "memo",
        "details",
    ),
    CANON_COUNTERPARTY: (
        "контрагент",
        "получатель",
        "отправитель",
        "корреспондент",
        "партнёр",
        "партнер",
        "counterparty",
        "payee",
        "merchant",
    ),
    CANON_CATEGORY: (
        "категория",
        "категорияоперации",
        "группа",
        "тип",
        "category",
    ),
    CANON_BALANCE: (
        "остаток",
        "остатокпосчету",
        "остатокпосчёту",
        "balance",
    ),
    CANON_MCC: ("mcc", "мсс", "мcс", "мккод"),
}

# Типовые «сигнатуры» банков: названия колонок / заголовков выписок.
BANK_SIGNATURES: dict[str, tuple[tuple[str, ...], ...]] = {
    "Сбер": (
        ("дата", "сумма", "операция"),
        ("датаоперации", "сумма", "категория"),
        ("датаплатежа", "датаобработки"),
    ),
    "Тинькофф": (
        ("датаоперации", "датаплатежа", "суммаоперации", "валютаоперации"),
        ("датаоперации", "суммаоперации", "категория", "mcc"),
    ),
    "Альфа-Банк": (
        ("датаоперации", "описаниеоперации", "суммавалютесчета"),
        ("дата", "референс", "суммавалютесчета"),
        ("дата", "описаниеоперации", "сумма"),
    ),
    "ВТБ": (
        ("датаоперации", "датаобработки", "суммавруб"),
        ("дата", "операция", "суммавруб"),
    ),
    "Газпромбанк": (
        ("датаоперации", "описание", "суммасписания", "суммазачисления"),
        ("дата", "описание", "приход", "расход"),
    ),
}


def _strip_key(s: str) -> str:
    """Нормализует имя колонки к сравнимому виду (только буквы, lower)."""
    return re.sub(r"[^a-zа-яё]", "", str(s).lower())


# ----------------------------- public API -------------------------------


def detect_bank(df: pd.DataFrame) -> str:
    """Опознать банк по набору колонок DataFrame.

    Возвращает имя банка или ``"Универсальный"``, если ни одна сигнатура
    не подошла.  Сравнение нечувствительно к регистру/пробелам/кавычкам.
    """

    columns_norm = {_strip_key(c) for c in df.columns}
    best_bank = "Универсальный"
    best_score = 0
    for bank, signatures in BANK_SIGNATURES.items():
        for signature in signatures:
            score = sum(1 for key in signature if any(key in col for col in columns_norm))
            if score > best_score and score >= max(2, len(signature) - 1):
                best_score = score
                best_bank = bank
    return best_bank


def _pick_column(df: pd.DataFrame, canonical: str) -> str | None:
    """Найти подходящую колонку DataFrame для канонического поля."""

    syns = COLUMN_SYNONYMS[canonical]
    columns_norm = {c: _strip_key(c) for c in df.columns}
    # точное совпадение
    for original, norm in columns_norm.items():
        if norm in syns:
            return original
    # подстрока: ищем ключ, содержащий синоним
    for original, norm in columns_norm.items():
        for syn in syns:
            if syn and syn in norm:
                return original
    return None


# ----------------------------- преобразование сумм ----------------------

_NUMBER_CLEAN_RE = re.compile(r"[^\d,.\-+]")


def _to_float(value: Any) -> float | None:
    """Безопасно привести значение к float с поддержкой ру-форматирования.

    Примеры валидных входов: ``"1 234,56"``, ``"1,234.56"``, ``"-500,00 ₽"``,
    ``"(500,00)"`` (скобки → отрицательное).
    """

    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        if pd.isna(value):
            return None
        return float(value)
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "-", "—"}:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1]
    s = _NUMBER_CLEAN_RE.sub("", s)
    if not s:
        return None
    # если встречаются и "," и "." — считаем "," разделителем тысяч
    if "," in s and "." in s:
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    # нормализуем несколько точек (тысячи)
    if s.count(".") > 1:
        last_dot = s.rfind(".")
        s = s[:last_dot].replace(".", "") + s[last_dot:]
    try:
        result = float(s)
    except ValueError:
        return None
    if negative:
        result = -abs(result)
    return result


def _parse_dates(series: pd.Series) -> pd.Series:
    """Устойчиво парсит даты: ру-формат, ISO, excel-номера."""

    import datetime as _dt

    def _one(v: Any) -> pd.Timestamp | None:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, pd.Timestamp):
            return v
        if isinstance(v, _dt.datetime):
            return pd.Timestamp(v)
        if isinstance(v, (int, float, np.integer, np.floating)):
            # excel serial (days since 1899-12-30)
            try:
                return pd.Timestamp("1899-12-30") + pd.to_timedelta(float(v), unit="D")
            except (ValueError, OverflowError):
                return None
        s = str(v).strip()
        if not s:
            return None
        for fmt in (
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%d.%m.%y",
        ):
            try:
                return pd.Timestamp(_dt.datetime.strptime(s, fmt))
            except ValueError:
                continue
        try:
            return pd.to_datetime(s, dayfirst=True, errors="raise")
        except (ValueError, TypeError):
            return None

    return series.map(_one)


# ----------------------------- классификация каналов --------------------


def _matches_any(text: str, keywords: Iterable[str]) -> bool:
    return any(kw in text for kw in keywords)


def infer_channel(description: str, category: str | None = None, amount: float = 0.0) -> str:
    """Эвристически определить канал операции.

    Возвращает один из каналов: ``p2p``, ``cash``, ``crypto``, ``gambling``,
    ``card``, ``online``, ``other``.
    """
    blob = f"{description or ''} {category or ''}".lower()
    if _matches_any(blob, CRYPTO_KEYWORDS):
        return "crypto"
    if _matches_any(blob, GAMBLING_KEYWORDS):
        return "gambling"
    if _matches_any(blob, CASH_KEYWORDS):
        return "cash"
    if _matches_any(blob, P2P_KEYWORDS):
        return "p2p"
    if any(k in blob for k in ("покуп", "оплата", "покупка", "mcc")):
        return "card"
    if any(k in blob for k in ("online", "интернет-магазин", "подписк")):
        return "online"
    return "other"


def _infer_type(amount: float | None) -> str:
    if amount is None:
        return "unknown"
    return "income" if amount > 0 else "expense"


# ----------------------------- нормализация -----------------------------


def normalize_dataframe(df: pd.DataFrame, bank: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Привести произвольный DataFrame к канонической схеме.

    Args:
        df: исходный DataFrame, уже прочитанный из файла.
        bank: опциональная подсказка по банку; если ``None`` — будет определён
            автоматически через :func:`detect_bank`.

    Returns:
        Кортеж ``(нормализованный_df, warnings)``.  ``warnings`` — список
        русских предупреждений, которые стоит показать пользователю.
    """

    warnings_: list[str] = []
    if bank is None:
        bank = detect_bank(df)

    # Специальные случаи: у Газпромбанка и иногда ВТБ есть отдельные
    # колонки «приход/расход» вместо одной подписанной «сумма».
    sum_col = _pick_column(df, CANON_AMOUNT)
    credit_col = next(
        (c for c in df.columns if _strip_key(c) in ("приход", "суммазачисления", "зачисление", "credit")),
        None,
    )
    debit_col = next(
        (c for c in df.columns if _strip_key(c) in ("расход", "суммасписания", "списание", "debit")),
        None,
    )

    date_col = _pick_column(df, CANON_DATE)
    if date_col is None:
        raise ValueError("Не удалось найти колонку с датой. Убедитесь, что в выписке есть столбец с датой операции.")

    if sum_col is None and not (credit_col and debit_col):
        raise ValueError(
            "Не удалось найти колонку с суммой. Ожидаются колонки 'Сумма операции' / 'Приход' и 'Расход'."
        )

    currency_col = _pick_column(df, CANON_CURRENCY)
    description_col = _pick_column(df, CANON_DESCRIPTION)
    counterparty_col = _pick_column(df, CANON_COUNTERPARTY)
    category_col = _pick_column(df, CANON_CATEGORY)
    balance_col = _pick_column(df, CANON_BALANCE)
    mcc_col = _pick_column(df, CANON_MCC)

    out = pd.DataFrame()
    out[CANON_DATE] = _parse_dates(df[date_col])

    if sum_col is not None:
        out[CANON_AMOUNT] = df[sum_col].map(_to_float)
    else:
        credit = df[credit_col].map(_to_float).fillna(0) if credit_col else 0.0
        debit = df[debit_col].map(_to_float).fillna(0) if debit_col else 0.0
        out[CANON_AMOUNT] = credit - debit.abs()

    out[CANON_CURRENCY] = df[currency_col].astype(str).str.upper() if currency_col else "RUB"
    out[CANON_DESCRIPTION] = df[description_col].astype(str) if description_col else ""
    out[CANON_COUNTERPARTY] = df[counterparty_col].astype(str) if counterparty_col else ""
    out[CANON_CATEGORY] = df[category_col].astype(str) if category_col else ""
    out[CANON_BALANCE] = df[balance_col].map(_to_float) if balance_col else np.nan
    out[CANON_MCC] = df[mcc_col] if mcc_col else np.nan

    # удаляем строки без даты или суммы — невозможно интерпретировать
    mask_valid = out[CANON_DATE].notna() & out[CANON_AMOUNT].notna()
    dropped = int((~mask_valid).sum())
    if dropped:
        warnings_.append(f"Пропущено {dropped} строк без даты или суммы.")
    out = out.loc[mask_valid].copy()

    # type + channel
    out[CANON_TYPE] = out[CANON_AMOUNT].map(_infer_type)
    out[CANON_CHANNEL] = [
        infer_channel(desc, cat, amt)
        for desc, cat, amt in zip(
            out[CANON_DESCRIPTION], out[CANON_CATEGORY], out[CANON_AMOUNT], strict=False
        )
    ]

    out = out[list(CANONICAL_COLUMNS)].sort_values(CANON_DATE).reset_index(drop=True)
    return out, warnings_


# ----------------------------- высокоуровневый API ----------------------


_READ_ERR = "Не удалось прочитать файл: {}"


def _read_any(
    source: str | Path | bytes | io.IOBase,
    filename_hint: str | None = None,
) -> pd.DataFrame:
    """Прочитать CSV/Excel/PDF в ``DataFrame``.

    Формат определяется по расширению; для потоков байт необходим
    ``filename_hint`` или magic-байты.
    """

    name = filename_hint or (source if isinstance(source, (str, Path)) else "")
    ext = Path(str(name)).suffix.lower()
    data: bytes | None = None
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    elif hasattr(source, "read"):
        data = source.read()

    if ext in {".xlsx", ".xls"}:
        engine = "openpyxl" if ext == ".xlsx" else None
        buf = io.BytesIO(data) if data is not None else source
        return pd.read_excel(buf, engine=engine)
    if ext == ".pdf":
        if data is None:
            with open(source, "rb") as fh:  # type: ignore[arg-type]
                data = fh.read()
        return _pdf_to_df(data)
    # CSV / TSV — пробуем несколько кодировок и разделителей
    buf = io.BytesIO(data) if data is not None else source
    return _read_csv_robust(buf)


def _read_csv_robust(buf: Any) -> pd.DataFrame:
    """Устойчивое чтение CSV: перебор кодировок/разделителей."""

    if hasattr(buf, "read"):
        raw = buf.read()
    elif isinstance(buf, (bytes, bytearray)):
        raw = bytes(buf)
    else:
        raw = Path(buf).read_bytes()
    last_err: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        for sep in (",", ";", "\t", "|"):
            try:
                df = pd.read_csv(
                    io.BytesIO(raw),
                    encoding=encoding,
                    sep=sep,
                    engine="python",
                    on_bad_lines="skip",
                    dtype=str,
                    keep_default_na=False,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                continue
            if df.shape[1] >= 2:
                return df
    raise ValueError(_READ_ERR.format(last_err))


_SBER_PDF_MARKERS: tuple[str, ...] = (
    "www.sberbank.ru",
    "СберБанк Онлайн",
    "Выписка по платёжному счёту",
    "Выписка по платежному счету",
    "ИТОГО ПО ОПЕРАЦИЯМ",
)

# Основная строка Sber-операции: DD.MM.YYYY HH:MM <категория> <+?сумма> <остаток>
_SBER_TX_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})\s+"
    r"(?P<time>\d{2}:\d{2})\s+"
    r"(?P<category>.+?)\s+"
    r"(?P<amount>\+?(?:\d+\s)*\d+,\d{2})\s+"
    r"(?P<balance>(?:\d+\s)*\d+,\d{2})\s*$"
)
# Строка продолжения: DD.MM.YYYY <код авторизации 4–8 цифр> <описание>
_SBER_CONT_RE = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<code>\d{4,8})\s+(?P<description>.+)$"
)


def _parse_sber_pdf_text(text: str) -> pd.DataFrame:
    """Разобрать текст PDF-выписки Сбера 2025–2026 (СберБанк Онлайн).

    Каждая операция занимает 2 строки: первая — дата+время+категория+сумма+остаток,
    вторая — дата+код авторизации+описание. Иногда описание переносится на
    третью строку (хвост типа ``****0880``).
    """
    records: list[dict[str, str]] = []
    cur: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _SBER_TX_RE.match(line)
        if m:
            if cur is not None:
                records.append(cur)
            cur = {
                "Дата операции": m.group("date"),
                "Время": m.group("time"),
                "Категория": m.group("category").strip(),
                "Сумма": m.group("amount"),
                "Остаток": m.group("balance"),
                "Описание": "",
                "Код авторизации": "",
            }
            continue
        m2 = _SBER_CONT_RE.match(line)
        if m2 and cur is not None and not cur["Описание"]:
            cur["Описание"] = m2.group("description").strip()
            cur["Код авторизации"] = m2.group("code")
            continue
        # короткий хвост (например "****0880") — добавляем к описанию текущей.
        # Игнорируем page-break артефакты: колонтитулы, футеры, номера страниц.
        if (
            cur is not None
            and cur["Описание"]
            and len(line) <= 30
            and line.startswith("*")
        ):
            cur["Описание"] = f"{cur['Описание']} {line}".strip()
    if cur is not None:
        records.append(cur)
    if not records:
        raise ValueError("Sber PDF: не найдено ни одной операции.")

    df = pd.DataFrame(records)
    # В Сбере знак `+` означает доход; иначе — расход. Приводим сумму в подписанный float,
    # чтобы нормализатор получил уже правильный знак.
    def _signed_amount(raw: str) -> float:
        stripped = raw.replace(" ", "").replace(",", ".")
        sign = 1.0 if stripped.startswith("+") else -1.0
        value = float(stripped.lstrip("+"))
        return sign * value

    df["Сумма"] = df["Сумма"].map(_signed_amount)
    df["Остаток"] = df["Остаток"].map(lambda s: float(s.replace(" ", "").replace(",", ".")))
    return df


def _pdf_to_df(data: bytes) -> pd.DataFrame:
    """PDF-парсер: отдельная ветка под Сбер, затем table extraction, затем regex.

    Стратегия:
      1. Читаем весь текст — если есть маркеры Сбера, идём специализированным
         парсером (`_parse_sber_pdf_text`), который понимает многострочный
         формат операции и знак «+» для поступлений.
      2. Иначе достаём все таблицы со всех страниц; берём самую широкую
         (по числу колонок) и объединяем построчно.
      3. Иначе — regex по тексту с жёсткой привязкой суммы к концу строки
         (чтобы не принимать 6-значный код авторизации за сумму).
    """
    import pdfplumber  # локальный импорт — тяжёлая зависимость

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    if any(m in text for m in _SBER_PDF_MARKERS):
        try:
            return _parse_sber_pdf_text(text)
        except ValueError:
            pass  # fallback на общий путь

    tables: list[list[list[str]]] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables() or []:
                if t and len(t) >= 2:
                    tables.append(t)
    if tables:
        widest = max(tables, key=lambda t: len(t[0]) if t else 0)
        header = [str(h or "").strip() for h in widest[0]]
        rows = [r for r in widest[1:] if any(cell is not None and str(cell).strip() for cell in r)]
        return pd.DataFrame(rows, columns=header)

    # fallback — regex по тексту, с жёсткой привязкой суммы к концу строки
    pattern = re.compile(
        r"^(?P<date>\d{2}[./-]\d{2}[./-]\d{2,4})\s+"
        r"(?P<description>.+?)\s+"
        r"(?P<amount>[-+]?(?:\d+[\s ])*\d+[.,]\d{2})\s*$"
    )
    records = []
    for line in text.splitlines():
        m = pattern.match(line.strip())
        if m:
            records.append(m.groupdict())
    if not records:
        raise ValueError("PDF не содержит распознаваемой таблицы операций.")
    return pd.DataFrame(records)


def parse_statement(
    source: str | Path | bytes | io.IOBase,
    *,
    filename_hint: str | None = None,
    bank_hint: str | None = None,
) -> tuple[pd.DataFrame, ParseInfo]:
    """Прочитать выписку и нормализовать её.

    Args:
        source: путь, bytes или файловый поток.
        filename_hint: оригинальное имя файла (нужен для bytes/стримов).
        bank_hint: если пользователь явно выбрал банк — передать сюда,
            парсер пропустит автодетект и возьмёт маппинг этого банка.

    Returns:
        ``(DataFrame, ParseInfo)``.  Транзакции отсортированы по дате.
    """
    df_raw = _read_any(source, filename_hint=filename_hint)
    bank = bank_hint or detect_bank(df_raw)
    df, warnings_ = normalize_dataframe(df_raw, bank=bank)

    currency = "RUB"
    if not df.empty:
        cur_values = df[CANON_CURRENCY].dropna().astype(str)
        if not cur_values.empty:
            currency = str(cur_values.mode().iloc[0])

    info = ParseInfo(
        bank=bank,
        rows_total=int(len(df_raw)),
        rows_parsed=int(len(df)),
        date_min=df[CANON_DATE].min() if not df.empty else None,
        date_max=df[CANON_DATE].max() if not df.empty else None,
        currency=currency,
        warnings=warnings_,
    )
    return df, info
