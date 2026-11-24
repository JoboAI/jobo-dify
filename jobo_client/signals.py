"""
Hiring signals in words, and as text a model can read.

A signal is one event at one company, detected from its job postings: a
hiring surge, a first job in a country, a leadership search. The API returns
the facts and leaves the wording to the reader. `describe_signal` is a port of
`describeSignal` in the connector core (`signal-summary.ts`), which writes the
sentences Jobo's own dashboard and alert emails use. Keep the two in step:
`tests/test_signal_summary.py` holds the same table of sentences as the core's
test.

Pure functions over the API's JSON. More signal types may be added: an unknown
type is put into words, never treated as an error.
"""

import math
import re
from typing import Any, Dict, Mapping, Optional

from jobo_client.format import _map, _number, _strings, _text

#: `type` values, in the API's own order.
SIGNAL_TYPES = (
    "hiring_surge",
    "new_function",
    "new_country",
    "leadership_hire",
    "new_skill",
    "hiring_slowdown",
    "first_role",
    "new_technology",
    "function_surge",
    "new_city",
    "hard_to_fill",
    "leadership_role_closed",
    "hiring_freeze",
    "hiring_resumed",
)

#: `seniority` values, lowest first.
SIGNAL_SENIORITY = ("junior", "mid", "senior", "director", "vp", "c_level", "executive")

#: Headcount bands, as returned in `company.size`.
SIGNAL_COMPANY_SIZES = (
    "1-10",
    "11-50",
    "51-200",
    "201-500",
    "501-1000",
    "1001-5000",
    "5001-10000",
    "10001+",
)

#: A short name for each signal type, as the dashboard shows it.
SIGNAL_TYPE_LABELS: Dict[str, str] = {
    "hiring_surge": "Hiring surge",
    "new_function": "New function",
    "new_country": "New country",
    "leadership_hire": "Leadership hire",
    "new_skill": "New skill",
    "hiring_slowdown": "Hiring slowdown",
    "first_role": "First role",
    "new_technology": "New technology",
    "function_surge": "Function surge",
    "new_city": "New city",
    "hard_to_fill": "Hard to fill",
    "leadership_role_closed": "Leadership role closed",
    "hiring_freeze": "Hiring freeze",
    "hiring_resumed": "Hiring resumed",
}

_THOUSANDS = re.compile(r"\B(?=(\d{3})+(?!\d))")


def signal_type_label(signal_type: Any) -> str:
    """The label of a type, or the type in words for one added after this was written."""
    known = SIGNAL_TYPE_LABELS.get(signal_type) if isinstance(signal_type, str) else None
    if known:
        return known
    words = ("" if signal_type is None else str(signal_type)).replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else "Signal"


def signal_strength_band(strength: float) -> str:
    """
    Strength in a word. Strength runs from 1 to 100 and compares signals of one
    type, so it reads better as one of four bands than as a score.
    """
    if strength >= 75:
        return "Very strong"
    if strength >= 50:
        return "Strong"
    if strength >= 25:
        return "Moderate"
    return "Mild"


def _round(value: float, digits: int) -> float:
    # Half away from zero, as the API rounds.
    factor = 10**digits
    magnitude = math.floor(abs(value) * factor + 1e-9 + 0.5) / factor
    return -magnitude if value < 0 else magnitude


def _plain(value: float) -> str:
    """A number as JavaScript's String() writes it: no ".0" on a whole number."""
    return str(int(value)) if value == int(value) else repr(value)


def _grouped(digits: str) -> str:
    return _THOUSANDS.sub(",", digits)


def _whole(value: float) -> str:
    return _grouped(_plain(_round(value, 0)))


def _decimal(value: float) -> str:
    """At most one decimal, and none when it would be ".0"."""
    integer, _, fraction = _plain(_round(value, 1)).partition(".")
    return f"{_grouped(integer)}.{fraction}" if fraction else _grouped(integer)


def _counted(count: float, noun: str) -> str:
    return f"1 {noun}" if abs(count - 1) < 0.0001 else f"{_whole(count)} {noun}s"


def _lookback(days: Optional[float]) -> str:
    if days is None or days <= 0:
        return "six months"
    if days < 60:
        return f"{_whole(days)} days"
    months = _round(days / 30, 0)
    return "six months" if months == 6 else f"{_plain(months)} months"


def describe_signal(signal: Mapping[str, Any]) -> str:
    """
    One plain sentence for a signal, e.g. "17 new jobs this week vs 3.1 a week
    normally". Falls back to the type's label when `details` lacks the facts
    the sentence needs, or the type is one this version does not know.
    """
    signal_type = signal.get("type")
    details = signal.get("details")
    if not isinstance(details, Mapping):
        return signal_type_label(signal_type)

    def number(name: str) -> Optional[float]:
        value = details.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(value) else None

    def text(name: str) -> Optional[str]:
        value = details.get(name)
        return value.strip() if isinstance(value, str) and value.strip() else None

    new_jobs = number("new_jobs")
    period = _lookback(number("lookback_days"))

    if signal_type == "hiring_surge":
        baseline = number("baseline_weekly_avg")
        if new_jobs is not None and baseline is not None:
            return f"{_counted(new_jobs, 'new job')} this week vs {_decimal(baseline)} a week normally"
    elif signal_type == "hiring_slowdown":
        now, before = number("open_roles"), number("open_roles_before")
        if now is not None and before is not None:
            change = number("change_pct")
            drop = abs(change if change is not None else 0.0)
            day = text("compared_to")
            since = f" since {day}" if day else ""
            return f"Open roles down {_decimal(drop)}%{since}: {_whole(now)} now, {_whole(before)} then"
    elif signal_type == "new_function":
        category = text("category")
        if category:
            if new_jobs is not None and new_jobs > 1:
                return f"{_counted(new_jobs, 'new job')} in {category}, a first in {period}"
            return f"First {category} job in {period}"
    elif signal_type == "new_country":
        country = text("country")
        if country:
            if new_jobs is not None and new_jobs > 1:
                return f"{_counted(new_jobs, 'new job')} in {country}, a first in {period}"
            return f"First job in {country} in {period}"
    elif signal_type == "new_skill":
        skill = text("skill")
        if skill:
            if new_jobs is not None and new_jobs > 1:
                return f"{_whole(new_jobs)} new jobs ask for {skill}, a first in {period}"
            return f"First job asking for {skill} in {period}"
    elif signal_type == "leadership_hire":
        title = text("title")
        if title:
            return f"Hiring a leader: {title}"
    elif signal_type == "first_role":
        occupation = text("occupation")
        if occupation:
            return f"First {occupation} role"
    elif signal_type == "new_technology":
        technology = text("technology")
        if technology:
            role = text("title")
            if role:
                return f"First mention of {technology}, in a {role} role"
            return f"First mention of {technology}"
    elif signal_type == "function_surge":
        category, usual = text("category"), number("baseline_avg")
        if category and new_jobs is not None and usual is not None:
            days = number("window_days")
            window = f"{_whole(days)} days" if days is not None else "two weeks"
            return (
                f"{_counted(new_jobs, f'new {category} job')} in {window} "
                f"vs {_decimal(usual)} normally"
            )
    elif signal_type == "new_city":
        city = text("city")
        if city:
            region = text("region")
            place = f"{city}, {region}" if region else city
            if new_jobs is not None and new_jobs > 1:
                return f"{_counted(new_jobs, 'new job')} in {place}, a first there"
            return f"First job in {place}"
    elif signal_type == "hard_to_fill":
        title, days_open = text("title"), number("days_open")
        if title and days_open is not None:
            city = text("city")
            at = f" ({city})" if city else ""
            if text("reason") != "reposted":
                return f"{title}{at} open {_counted(days_open, 'day')}"
            closed = number("closed_days")
            if closed is not None and closed > 0:
                return f"{title}{at} re-posted after {_counted(closed, 'day')} closed"
            return f"{title}{at} re-posted"
    elif signal_type == "leadership_role_closed":
        # Says the posting ended, never that anyone was hired.
        title, days_open = text("title"), number("days_open")
        if title and days_open is not None:
            return f"{title} search closed after {_counted(days_open, 'day')}"
    elif signal_type == "hiring_freeze":
        removed, had = number("closed_jobs"), number("open_roles_before")
        if removed is not None and had is not None:
            last = text("closed_to")
            week = f" in the week to {last}" if last else ""
            return f"{_whole(removed)} of {_counted(had, 'open role')} removed{week}"
    elif signal_type == "hiring_resumed":
        gap = number("gap_days")
        if gap is not None:
            return f"First new job in {_counted(gap, 'day')}"

    return signal_type_label(signal_type)


# ------------------------------------------------------------------ rendering


EMPTY_SIGNALS = (
    "No hiring signals matched. Nothing was billed: an empty result is free. "
    "Widen a filter or the date range; values such as functions, technologies "
    "and industries match only as Jobo records them."
)


def signals_header(shown: int, has_more: bool, next_cursor: Optional[str]) -> str:
    """The line above a page of signals: how many, and whether more remain."""
    header = f"{shown} hiring signal{'' if shown == 1 else 's'}, newest detection day first."
    if has_more and next_cursor:
        return (
            f"{header} More remain: pass cursor \"{next_cursor}\" with the same filters "
            "to read the next page, which is billed again per signal."
        )
    return f"{header} No more remain."


def format_signal(signal: Mapping[str, Any], index: int) -> str:
    """Render one signal as a compact, citeable block."""
    company = _map(signal.get("company"))
    name = _text(company.get("name")) or "Unnamed company"
    domain = _text(company.get("domain"))
    title = f"{index}. {name} ({domain})" if domain else f"{index}. {name}"
    lines = [f"{title} - {signal_type_label(signal.get('type'))}", describe_signal(signal)]
    facts = []
    detected = _text(signal.get("detected_on"))
    if detected:
        facts.append(f"Detected: {detected}")
    strength = _number(signal.get("strength"))
    if strength is not None:
        facts.append(f"Strength: {_plain(strength)} of 100 ({signal_strength_band(strength)})")
    if facts:
        lines.append(" | ".join(facts))
    evidence = _strings(signal.get("evidence_job_ids"))
    if evidence:
        lines.append(f"Evidence job ids (free with get_job): {', '.join(evidence)}")
    if _text(company.get("id")):
        lines.append(f"Company ID: {_text(company.get('id'))}")
    return "\n".join([lines[0], *(f"   {line}" for line in lines[1:])])


def signals_billing_line(count: int) -> str:
    """The last line of a result: how many signals this call was billed for."""
    if count == 0:
        return "Billing: no signals returned, so nothing was billed."
    return (
        f"Billing: {count} signal{'' if count == 1 else 's'} returned, each billed at ten "
        "times the price of a job unless the plan covers it. Reading the same signals "
        "again bills them again."
    )


def signal_metadata(signal: Mapping[str, Any]) -> Dict[str, Any]:
    """The signal as the API returned it, plus its type label and summary sentence."""
    return {
        **signal,
        "type_label": signal_type_label(signal.get("type")),
        "summary": describe_signal(signal),
    }
