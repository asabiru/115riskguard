"""Локальное хранилище истории анализов в SQLite.

Одна таблица — ``analyses`` — хранит JSON-снепшот каждой проанализированной
выписки: метаданные, итоговый балл, список флагов и признаки.  Никакие
платёжные данные не пересылаются наружу — файл БД лежит рядом с репо,
по умолчанию в ``data/history.db``.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .feature_engineering import StatementFeatures
from .risk_engine import RiskAssessment

DEFAULT_DB_PATH = Path("data/history.db")


# ------------------------------- schema -------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    bank TEXT,
    date_min TEXT,
    date_max TEXT,
    rows_parsed INTEGER,
    risk_score REAL,
    probability REAL,
    level TEXT,
    red_flags INTEGER,
    yellow_flags INTEGER,
    features_json TEXT NOT NULL,
    flags_json TEXT NOT NULL,
    meta_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_analyses_created ON analyses(created_at);
"""


@contextmanager
def _connect(db_path: str | Path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Создать таблицы, если их ещё нет (идемпотентно)."""
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def save_analysis(
    features: StatementFeatures,
    assessment: RiskAssessment,
    *,
    bank: str,
    date_min: datetime | None,
    date_max: datetime | None,
    rows_parsed: int,
    meta: dict[str, Any] | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    """Сохранить анализ в БД и вернуть ``id`` новой записи."""
    init_db(db_path)
    red = sum(1 for f in assessment.flags if f.severity == "red")
    yellow = sum(1 for f in assessment.flags if f.severity == "yellow")
    payload_features = features.to_dict()
    payload_flags = [asdict(f) for f in assessment.flags]
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO analyses (
                created_at, bank, date_min, date_max, rows_parsed,
                risk_score, probability, level, red_flags, yellow_flags,
                features_json, flags_json, meta_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                datetime.utcnow().isoformat(timespec="seconds"),
                bank,
                date_min.isoformat() if date_min is not None else None,
                date_max.isoformat() if date_max is not None else None,
                int(rows_parsed),
                float(assessment.risk_score),
                float(assessment.probability),
                assessment.level.value,
                int(red),
                int(yellow),
                json.dumps(payload_features, ensure_ascii=False),
                json.dumps(payload_flags, ensure_ascii=False, default=str),
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid or 0)


def list_analyses(
    limit: int = 50, db_path: str | Path = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    """Вернуть последние ``limit`` записей истории (без тяжёлых JSON-полей)."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, bank, date_min, date_max, rows_parsed,
                   risk_score, probability, level, red_flags, yellow_flags
            FROM analyses
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def load_analysis(
    analysis_id: int, db_path: str | Path = DEFAULT_DB_PATH
) -> dict[str, Any] | None:
    """Загрузить полную запись анализа по id (распарсив все JSON-поля)."""
    init_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id=?", (int(analysis_id),)).fetchone()
    if row is None:
        return None
    data = dict(row)
    for key in ("features_json", "flags_json", "meta_json"):
        val = data.get(key)
        if val:
            try:
                data[key.replace("_json", "")] = json.loads(val)
            except json.JSONDecodeError:
                data[key.replace("_json", "")] = None
    return data


def delete_analysis(analysis_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> bool:
    """Удалить запись по id; вернуть ``True``, если удалено."""
    init_db(db_path)
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM analyses WHERE id=?", (int(analysis_id),))
        return cur.rowcount > 0
