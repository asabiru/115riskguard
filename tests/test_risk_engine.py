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
    f.p2p_incoming_count = 2
    f.p2p_last30d = 3
    f.p2p_unique_counterparties = 2
    f.p2p_max_per_day = 1
    f.same_day_turnover_share = 0.1
    f.residual_ratio = 0.4
    f.cash_ratio = 0.05
    f.has_salary_anchor = True
    # аккуратно «живой» счёт — есть покупки, нет признаков batch-2 рисков
    f.card_purchases_count = 40
    f.avg_p2p_amount = 7_500
    f.one_dominant_sender_share = 0.2
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
    f.gambling_ops_count = 20
    f.incoming_unique_counterparties = 55
    f.incoming_from_individuals_count = 30
    f.turnover_spike_ratio = 7.0
    f.new_counterparty_share = 0.8
    f.night_tx_ratio = 0.3
    f.largest_income = 700_000
    # новые паттерны (banki.ru 2025–2026)
    f.fast_inout_share = 0.6
    f.fast_inout_pairs_count = 50
    f.has_lifestyle_payments = False
    f.days_without_lifestyle = 60
    f.active_hours_span = 23
    f.active_hours_avg_per_day = 20.0
    f.sbp_out_after_income_share = 0.85
    f.third_party_cash_deposits_count = 12
    f.ip_samozanyat_transfers_count = 40
    f.collective_fundraising_max_unique = 25
    f.new_senders_share = 0.9
    # вторая волна паттернов (100+ кейсов banki.ru 2025–2026)
    f.round_amounts_share = 0.8
    f.identical_amount_max_repeats = 15
    f.salary_day_drain_ratio = 0.95
    f.dormant_days_before_spike = 45
    f.multi_bank_fanout_max = 9
    f.cross_border_transfers_count = 6
    f.avg_p2p_amount = 900
    f.atm_cashout_after_income_ratio = 0.8
    f.one_dominant_sender_share = 0.9
    f.rejected_operations_count = 10
    f.card_purchases_count = 0
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


# ----- правила, добавленные после разбора banki.ru 2025–2026 -----


def test_fast_in_out_triggers():
    f = _clean_features()
    f.fast_inout_share = 0.5
    f.fast_inout_pairs_count = 20
    a = assess_risk(f)
    assert any(flag.rule_id == "fast_in_out" and flag.severity == "red" for flag in a.flags)


def test_no_lifestyle_payments_triggers():
    f = _clean_features()
    f.days_without_lifestyle = 60
    f.has_lifestyle_payments = False
    a = assess_risk(f)
    assert any(flag.rule_id == "no_lifestyle_payments" for flag in a.flags)


def test_crypto_gambling_combo_red():
    f = _clean_features()
    f.crypto_ops_count = 5
    f.gambling_ops_count = 5
    a = assess_risk(f)
    combo = [flag for flag in a.flags if flag.rule_id == "crypto_gambling_combo"]
    assert combo and combo[0].severity == "red"


def test_sbp_out_after_income_triggers():
    f = _clean_features()
    f.sbp_out_after_income_share = 0.8
    a = assess_risk(f)
    assert any(flag.rule_id == "sbp_out_after_income" and flag.severity == "red" for flag in a.flags)


def test_third_party_cash_deposits_triggers():
    f = _clean_features()
    f.third_party_cash_deposits_count = 10
    a = assess_risk(f)
    assert any(flag.rule_id == "third_party_cash_deposits" for flag in a.flags)


def test_ip_samozanyat_triggers():
    f = _clean_features()
    f.ip_samozanyat_transfers_count = 30
    a = assess_risk(f)
    assert any(flag.rule_id == "ip_samozanyat_transfers" and flag.severity == "red" for flag in a.flags)


def test_collective_fundraising_triggers():
    f = _clean_features()
    f.collective_fundraising_max_unique = 25
    a = assess_risk(f)
    assert any(flag.rule_id == "collective_fundraising" and flag.severity == "red" for flag in a.flags)


def test_new_senders_dominance_triggers():
    f = _clean_features()
    f.new_senders_share = 0.9
    a = assess_risk(f)
    assert any(flag.rule_id == "new_senders_dominance" and flag.severity == "red" for flag in a.flags)


def test_round_the_clock_triggers():
    f = _clean_features()
    f.active_hours_span = 23
    f.active_hours_avg_per_day = 20.0
    a = assess_risk(f)
    assert any(flag.rule_id == "round_the_clock" and flag.severity == "red" for flag in a.flags)


# ----- правила, добавленные во второй волне (100+ кейсов banki.ru 2025–2026) -----


def test_round_amounts_pattern_triggers():
    f = _clean_features()
    f.p2p_incoming_count = 30
    f.round_amounts_share = 0.8
    a = assess_risk(f)
    assert any(flag.rule_id == "round_amounts_pattern" and flag.severity == "red" for flag in a.flags)


def test_identical_amount_repeats_triggers():
    f = _clean_features()
    f.identical_amount_max_repeats = 15
    a = assess_risk(f)
    assert any(flag.rule_id == "identical_amount_repeats" and flag.severity == "red" for flag in a.flags)


def test_salary_day_drain_triggers():
    f = _clean_features()
    f.salary_day_drain_ratio = 0.95
    a = assess_risk(f)
    assert any(flag.rule_id == "salary_day_drain" and flag.severity == "red" for flag in a.flags)


def test_dormant_then_active_triggers():
    f = _clean_features()
    f.days_observed = 120
    f.dormant_days_before_spike = 70
    a = assess_risk(f)
    assert any(flag.rule_id == "dormant_then_active" and flag.severity == "red" for flag in a.flags)


def test_multi_bank_fanout_triggers():
    f = _clean_features()
    f.multi_bank_fanout_max = 10
    a = assess_risk(f)
    assert any(flag.rule_id == "multi_bank_fanout" and flag.severity == "red" for flag in a.flags)


def test_cross_border_transfers_triggers():
    f = _clean_features()
    f.cross_border_transfers_count = 7
    a = assess_risk(f)
    assert any(flag.rule_id == "cross_border_transfers" and flag.severity == "red" for flag in a.flags)


def test_very_low_avg_amount_triggers():
    f = _clean_features()
    f.p2p_count = 50
    f.avg_p2p_amount = 900
    a = assess_risk(f)
    assert any(flag.rule_id == "very_low_avg_amount" and flag.severity == "red" for flag in a.flags)


def test_atm_cashout_after_income_triggers():
    f = _clean_features()
    f.atm_cashout_after_income_ratio = 0.9
    a = assess_risk(f)
    assert any(flag.rule_id == "atm_cashout_after_income" and flag.severity == "red" for flag in a.flags)


def test_one_dominant_sender_triggers():
    f = _clean_features()
    f.p2p_incoming_count = 20
    f.one_dominant_sender_share = 0.9
    a = assess_risk(f)
    assert any(flag.rule_id == "one_dominant_sender" and flag.severity == "red" for flag in a.flags)


def test_new_card_burst_triggers():
    f = _clean_features()
    f.days_observed = 10
    f.turnover_total = 900_000
    a = assess_risk(f)
    assert any(flag.rule_id == "new_card_burst" and flag.severity == "red" for flag in a.flags)


def test_rejected_operations_triggers():
    f = _clean_features()
    f.rejected_operations_count = 10
    a = assess_risk(f)
    assert any(flag.rule_id == "rejected_operations" and flag.severity == "red" for flag in a.flags)


def test_no_card_purchases_triggers():
    f = _clean_features()
    f.card_purchases_count = 0
    f.tx_count = 40
    a = assess_risk(f)
    assert any(flag.rule_id == "no_card_purchases" for flag in a.flags)
