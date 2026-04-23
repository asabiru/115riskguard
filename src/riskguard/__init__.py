"""115RiskGuard — индивидуальный риск-контроль по 115-ФЗ.

Пакет реализует локальный пайплайн анализа банковских выписок физического
лица и оценивает вероятность блокировки/приостановки счёта банком по 115-ФЗ.

Модули:
    * :mod:`riskguard.parser` — чтение и нормализация выписок разных банков.
    * :mod:`riskguard.feature_engineering` — подсчёт поведенческих признаков.
    * :mod:`riskguard.risk_engine` — гибридная rule+ML-оценка риска.
    * :mod:`riskguard.report_generator` — экспорт отчётов в PDF/Excel.
    * :mod:`riskguard.storage` — локальное хранение истории анализов в SQLite.
    * :mod:`riskguard.constants` — пороги, веса и справочники.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
