"""
Hiring signals in words: the port of the connector core's `describeSignal`.

The table is the one in `packages/connector-core/src/signal-summary.test.ts`,
which holds the sentences Jobo's dashboard and alert emails write. Keep the
two in step.
"""

import pytest

from jobo_client.signals import (
    SIGNAL_TYPE_LABELS,
    SIGNAL_TYPES,
    describe_signal,
    signal_strength_band,
    signal_type_label,
)


def say(signal_type, details):
    return describe_signal({"type": signal_type, "details": details})


def test_every_type_the_api_has_has_a_label():
    assert list(SIGNAL_TYPE_LABELS) == list(SIGNAL_TYPES)


def test_a_type_added_later_is_put_into_words_rather_than_failing():
    assert signal_type_label("remote_shift") == "Remote shift"
    assert signal_type_label("") == "Signal"
    assert signal_type_label(None) == "Signal"


def test_strength_reads_as_one_of_four_bands():
    assert [signal_strength_band(s) for s in (100, 75, 74, 50, 49, 25, 24, 1)] == [
        "Very strong", "Very strong", "Strong", "Strong", "Moderate", "Moderate", "Mild", "Mild",
    ]


@pytest.mark.parametrize(
    "signal_type, details, sentence",
    [
        ("hiring_surge", {"new_jobs": 17, "baseline_weekly_avg": 3.1}, "17 new jobs this week vs 3.1 a week normally"),
        ("hiring_surge", {"new_jobs": 1, "baseline_weekly_avg": 0.04}, "1 new job this week vs 0 a week normally"),
        (
            "hiring_surge",
            {"new_jobs": 1200, "baseline_weekly_avg": 1050.25},
            "1,200 new jobs this week vs 1,050.3 a week normally",
        ),
        (
            "hiring_slowdown",
            {"open_roles": 40, "open_roles_before": 90, "change_pct": -55.6, "compared_to": "2026-09-21"},
            "Open roles down 55.6% since 2026-09-21: 40 now, 90 then",
        ),
        ("new_function", {"category": "Sales", "new_jobs": 4, "lookback_days": 180}, "4 new jobs in Sales, a first in six months"),
        ("new_function", {"category": "Sales", "lookback_days": 90}, "First Sales job in 3 months"),
        ("new_country", {"country": "Germany", "new_jobs": 1}, "First job in Germany in six months"),
        ("new_country", {"country": "Germany", "new_jobs": 3, "lookback_days": 45}, "3 new jobs in Germany, a first in 45 days"),
        ("new_skill", {"skill": "Rust", "new_jobs": 5}, "5 new jobs ask for Rust, a first in six months"),
        ("new_skill", {"skill": "Rust", "named": True}, "First job asking for Rust in six months"),
        ("leadership_hire", {"title": "VP of Engineering"}, "Hiring a leader: VP of Engineering"),
        ("first_role", {"occupation": "Data Engineer"}, "First Data Engineer role"),
        (
            "new_technology",
            {"technology": "Snowflake", "title": "Data Engineer"},
            "First mention of Snowflake, in a Data Engineer role",
        ),
        ("new_technology", {"technology": "Snowflake"}, "First mention of Snowflake"),
        (
            "function_surge",
            {"category": "Technology", "new_jobs": 12, "baseline_avg": 2.5, "window_days": 14},
            "12 new Technology jobs in 14 days vs 2.5 normally",
        ),
        (
            "function_surge",
            {"category": "Technology", "new_jobs": 1, "baseline_avg": 0.2},
            "1 new Technology job in two weeks vs 0.2 normally",
        ),
        ("new_city", {"city": "Austin", "region": "Texas", "new_jobs": 6}, "6 new jobs in Austin, Texas, a first there"),
        ("new_city", {"city": "Austin"}, "First job in Austin"),
        ("hard_to_fill", {"title": "Staff Nurse", "days_open": 92, "city": "Leeds"}, "Staff Nurse (Leeds) open 92 days"),
        (
            "hard_to_fill",
            {"title": "Staff Nurse", "days_open": 30, "reason": "reposted", "closed_days": 1},
            "Staff Nurse re-posted after 1 day closed",
        ),
        ("hard_to_fill", {"title": "Staff Nurse", "days_open": 30, "reason": "reposted"}, "Staff Nurse re-posted"),
        (
            "leadership_role_closed",
            {"title": "Chief Financial Officer", "days_open": 61},
            "Chief Financial Officer search closed after 61 days",
        ),
        (
            "hiring_freeze",
            {"closed_jobs": 45, "open_roles_before": 52, "closed_to": "2026-11-15"},
            "45 of 52 open roles removed in the week to 2026-11-15",
        ),
        ("hiring_resumed", {"gap_days": 74}, "First new job in 74 days"),
    ],
)
def test_one_sentence_per_signal(signal_type, details, sentence):
    assert say(signal_type, details) == sentence


def test_falls_back_to_the_type_label_when_the_facts_are_missing():
    assert say("hiring_surge", {"new_jobs": 17}) == "Hiring surge"
    assert say("leadership_hire", {}) == "Leadership hire"
    assert describe_signal({"type": "new_city", "details": None}) == "New city"
    assert describe_signal({"type": "new_city", "details": ["Austin"]}) == "New city"


def test_a_boolean_is_not_read_as_a_number():
    assert say("hiring_resumed", {"gap_days": True}) == "Hiring resumed"


def test_names_a_type_it_does_not_know_instead_of_failing():
    assert say("remote_shift", {"share": 0.4}) == "Remote shift"
