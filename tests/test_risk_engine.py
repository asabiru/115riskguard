"""Тесты rule-based движка."""

from __future__ import annotations

from riskguard.constants import DEFAULT_THRESHOLDS, RiskLevel
from riskguard.feature_engineering import StatementFeatures
from riskguard.risk_engine import assess_risk, whatif_adjust_features


def _clean_features() -> StatementFeatures:
    f = StatementFeatures()
    f.days_observed = 30
    f.tx_count = 80
    f.income_total = 90_000
    f.expense_total = 80_000
    f.net_flow = 10_000
    f.turnover_total = 170_000
    f.monthly_turnover = 170_000
    f.p2p_count = 3
    f.p2p_last30d = 3
    f.p2p_unique_counterparties = 2
    f.p2p_max_per_day = 1
    f.same_day_turnover_share = 0.1
    f.residual_ratio = 0.4
    f.cash_ratio = 0.05
    f.has_salary_anchor = True
    return f


def _risky_features() -> StatementFeatures:
    f = StatementFeatures()
    f.days_observed = 30
    f.tx_count = 400
    f.income_total = 900_000
    f.expense_total = 890_000
    f.net_flow = 10_000
    f.turnover_total = 1_790_000
    f.monthly_turnover = 1_790_000
    f.p2p_count = 300
    f.p2p_last30d = 200
    f.p2p_unique_counterparties = 80
    f.p2p_max_per_day = 35
    f.same_day_turnover_share = 0.95
    f.residual_ratio = 0.01
    f.cash_ratio = 0.6
    f.crypto_ops_count = 12
    f.incoming_unique_counterparties = 55
    f.incoming_from_individuals_count = 30
    f.turnover_spike_ratio = 7.0
    f.new_counterparty_share = 0.8
    f.night_tx_ratio = 0.3
    f.largest_income = 700_000
    return f


def test_clean_statement_is_green():
    assessment = assess_risk(_clean_features(), thresholds=DEFAULT_THRESHOLDS)
    assert assessment.level == RiskLevel.GREEN
    assert assessment.flags == [] or all(f.severity != "red" for f in assessment.flags)


def test_risky_statement_is_red():
    assessment = assess_risk(_risky_features(), thresholds=DEFAULT_THRESHOLDS)
    assert assessment.level == RiskLevel.RED
    assert any(f.severity == "red" for f in assessment.flags)
    # должны сработать все ключевые правила
    rules_fired = {f.rule_id for f in assessment.flags}
    assert "p2p_daily_spike" in rules_fired
    assert "transit_activity" in rules_fired
    assert "crypto_exchange" in rules_fired


def test_whatif_increases_risk():
    base = _clean_features()
    base_score = assess_risk(base).risk_score
    boosted = whatif_adjust_features(base, add_p2p_30d=80, add_crypto_ops=10, add_cash_share=0.4)
    new_score = assess_risk(boosted).risk_score
    assert new_score > base_score


def test_ml_blend_monotonic():
    base = _clean_features()
    low = assess_risk(base, ml_probability=0.05).risk_score
    high = assess_risk(base, ml_probability=0.95).risk_score
    assert high >= low
