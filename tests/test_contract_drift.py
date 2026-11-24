"""
Drift guard against the shared connector filter contract.

`Jobo.Connectors/contracts/filters.json` is generated from the connector core
and lists every search filter the Jobo connectors support. These tests fail
when the contract gains a filter search_jobs does not take or does not send,
or when an enum here stops matching it. `contracts/signals.json` does the
same for list_hiring_signals (see the section at the end).

The contract lives one directory above this plugin in the Jobo monorepo. The
plugin is mirrored to a public repository on its own, and there the file is
absent, so the module is skipped.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from jobo_client.client import JoboClient
from jobo_client.format import FACET_FILTERS
from jobo_client.service import (
    COMPANY_CATEGORIES,
    EMPLOYMENT_TYPES,
    EXPERIENCE_LEVELS,
    FILTER_FACETS,
    SORTS,
    WORK_MODELS,
    JoboService,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT.parent / "contracts" / "filters.json"

pytestmark = pytest.mark.skipif(
    not CONTRACT_PATH.is_file(),
    reason="filters.json is only present inside the Jobo.Connectors monorepo",
)

#: Contract keys whose search_jobs parameter has another name.
CONTRACT_KEY_TO_PARAMETER = {"q": "query"}

#: Contract filters search_jobs leaves out on purpose, with the reason.
LEFT_OUT = {
    # search_jobs never shows a description: its text and JSON carry the
    # summary fields only, so the format would change nothing the model sees.
    "description_format": "search_jobs output has no description",
}

#: search_jobs parameters that are paging, not filters.
PAGING = {"page", "page_size"}

#: A sample value per contract `kind`, written the way Dify passes it.
SAMPLE_BY_KIND: Dict[str, Any] = {
    "string": "sample",
    "number": 123,
    "boolean": False,
    "dateTime": "2026-11-01T00:00:00Z",
    "stringList": "sample",
}


def contract() -> Dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def search_filters() -> List[Dict[str, Any]]:
    return contract()["search_filters"]


def parameter_for(key: str) -> str:
    return CONTRACT_KEY_TO_PARAMETER.get(key, key)


def tool_parameters() -> Dict[str, Dict[str, Any]]:
    tool = yaml.safe_load((ROOT / "tools/search_jobs.yaml").read_text(encoding="utf-8"))
    return {p["name"]: p for p in tool["parameters"]}


def sample_for(descriptor: Dict[str, Any]) -> Any:
    kind = descriptor["kind"]
    options: List[str] = descriptor.get("options") or []
    if kind == "enum":
        # The last option is never the API default, which is not sent.
        return options[-1]
    if kind == "enumList":
        return options[0] if options else "sample"
    return SAMPLE_BY_KIND[kind]


def test_contract_was_found_and_has_filters():
    assert len(search_filters()) >= 30


def test_search_jobs_takes_every_search_filter_in_the_contract():
    parameters = tool_parameters()
    missing = sorted(
        d["key"]
        for d in search_filters()
        if d["key"] not in LEFT_OUT and parameter_for(d["key"]) not in parameters
    )
    assert missing == [], f"filters.json has search filters search_jobs lacks: {missing}"


def test_search_jobs_has_no_filter_the_contract_does_not_know():
    known = {parameter_for(d["key"]) for d in search_filters()}
    extra = sorted(set(tool_parameters()) - known - PAGING)
    assert extra == []


def test_left_out_filters_are_real_contract_keys():
    keys = {d["key"] for d in search_filters()}
    assert set(LEFT_OUT) <= keys
    assert not set(LEFT_OUT) & set(tool_parameters())


def test_every_search_filter_reaches_the_request_body():
    """A parameter that validates but is never sent would be a silent no-op."""
    service = JoboService(JoboClient("jbe_test_drift"))
    baseline, _ = service.search_request({})
    unsent = []
    for descriptor in search_filters():
        if descriptor["key"] in LEFT_OUT:
            continue
        args = {parameter_for(descriptor["key"]): sample_for(descriptor)}
        body, _ = service.search_request(args)
        if body == baseline:
            unsent.append(descriptor["key"])
    assert unsent == []


@pytest.mark.parametrize(
    "contract_enum, values",
    [
        ("work_models", WORK_MODELS),
        ("employment_types", EMPLOYMENT_TYPES),
        ("experience_levels", EXPERIENCE_LEVELS),
        ("company_categories", COMPANY_CATEGORIES),
        ("search_sorts", SORTS),
    ],
)
def test_enum_values_match_the_contract(contract_enum, values):
    assert list(values) == contract()["enums"][contract_enum]


def test_sort_options_in_the_schema_match_the_contract():
    by_key = {d["key"]: d for d in search_filters()}
    options = [o["value"] for o in tool_parameters()["sort"]["options"]]
    assert options == by_key["sort"]["options"]


@pytest.mark.parametrize(
    "key", ["work_model", "employment_type", "experience_level", "company_categories"]
)
def test_enum_parameters_name_every_contract_option(key):
    """The model only learns a closed list's values from the description."""
    by_key = {d["key"]: d for d in search_filters()}
    description = tool_parameters()[key]["llm_description"]
    missing = [o for o in by_key[key]["options"] if o not in description]
    assert missing == [], key


def test_lookup_facets_are_the_dynamic_option_sources_of_the_contract():
    """
    find_filter_values lists every value set the contract loads at run time.

    `companies` is the one source it does not list: find_companies does.
    """
    sources = {d["dynamicOptions"] for d in search_filters() if "dynamicOptions" in d}
    lookup = yaml.safe_load(
        (ROOT / "tools/find_filter_values.yaml").read_text(encoding="utf-8")
    )
    facet = next(p for p in lookup["parameters"] if p["name"] == "facet")

    assert set(FILTER_FACETS) == sources - {"companies"}
    assert {o["value"] for o in facet["options"]} == set(FILTER_FACETS)
    assert set(FACET_FILTERS) == set(FILTER_FACETS)


def test_each_lookup_facet_points_at_a_search_jobs_parameter():
    """find_filter_values tells the model which filter to fill: it must exist."""
    by_key = {d["key"]: d for d in search_filters()}
    parameters = tool_parameters()
    for facet, filter_name in FACET_FILTERS.items():
        assert filter_name in parameters, facet
        assert by_key[filter_name]["dynamicOptions"] == facet


# ------------------------------------------------------------ hiring signals
#
# `contracts/signals.json` is generated from the core's `signals.ts` the same
# way: the filters of `GET /api/signals`, their kinds and enum values, which
# ones `GET /api/companies/{id}/signals` takes, and the type labels.

SIGNALS_PATH = ROOT.parent / "contracts" / "signals.json"
signals_contract_present = pytest.mark.skipif(
    not SIGNALS_PATH.is_file(),
    reason="signals.json is only present inside the Jobo.Connectors monorepo",
)

#: Signals filters list_hiring_signals leaves out on purpose, with the reason.
#: An agent picks a few filters per call; each one here is either served by
#: another parameter or narrows to a corner few questions need.
SIGNALS_LEFT_OUT = {
    "company_ids": "company_id reads one company's signals; domains picks several companies",
    "exclude_domains": "an agent asks for companies, rarely for every company but some",
    "categories": "company categories overlap industries, which the tool takes",
    "founded_after": "rarely asked of a signal; funding_stages covers company age",
    "technology_categories": "technologies and skills name the tools an agent is asked about",
    "job_regions": "job_countries covers where the jobs are; regions are free text",
    "job_cities": "only new_city and hard_to_fill record a city",
    "min_new_jobs": "a threshold on two types only; min_strength ranks every type",
    "min_days_open": "a threshold on hard_to_fill only",
    "reposted_only": "a switch on hard_to_fill only",
}

#: list_hiring_signals parameters that are not filters of the contract.
SIGNALS_NOT_FILTERS = {"company_id", "limit", "cursor"}

#: A sample value per signals filter `kind`, written the way Dify passes it.
SIGNALS_SAMPLE_BY_KIND: Dict[str, Any] = {
    "stringList": "sample",
    "boolean": True,
    "date": "2026-11-01",
    "dateTime": "2026-11-01T00:00:00Z",
}
#: Lists whose values must be two-letter country codes.
SIGNALS_COUNTRY_KEYS = {"countries", "job_countries"}


def signals_contract() -> Dict[str, Any]:
    return json.loads(SIGNALS_PATH.read_text(encoding="utf-8"))


def signals_tool_parameters() -> Dict[str, Dict[str, Any]]:
    tool = yaml.safe_load(
        (ROOT / "tools/list_hiring_signals.yaml").read_text(encoding="utf-8")
    )
    return {p["name"]: p for p in tool["parameters"]}


def signals_sample(descriptor: Dict[str, Any]) -> Any:
    kind = descriptor["kind"]
    if kind == "enumList":
        return descriptor["options"][-1]
    if kind == "number":
        return descriptor.get("min", 1)
    if descriptor["key"] in SIGNALS_COUNTRY_KEYS:
        return "US"
    return SIGNALS_SAMPLE_BY_KIND[kind]


@signals_contract_present
def test_list_hiring_signals_takes_every_signals_filter_not_left_out():
    parameters = signals_tool_parameters()
    missing = sorted(
        d["key"]
        for d in signals_contract()["filters"]
        if d["key"] not in SIGNALS_LEFT_OUT and d["key"] not in parameters
    )
    assert missing == [], f"signals.json has filters list_hiring_signals lacks: {missing}"


@signals_contract_present
def test_list_hiring_signals_has_no_filter_the_contract_does_not_know():
    known = {d["key"] for d in signals_contract()["filters"]}
    extra = sorted(set(signals_tool_parameters()) - known - SIGNALS_NOT_FILTERS)
    assert extra == []


@signals_contract_present
def test_signals_left_out_filters_are_real_contract_keys():
    keys = {d["key"] for d in signals_contract()["filters"]}
    assert set(SIGNALS_LEFT_OUT) <= keys
    assert not set(SIGNALS_LEFT_OUT) & set(signals_tool_parameters())


@signals_contract_present
def test_signals_enums_and_labels_match_the_contract():
    from jobo_client.signals import (
        SIGNAL_COMPANY_SIZES,
        SIGNAL_SENIORITY,
        SIGNAL_TYPE_LABELS,
        SIGNAL_TYPES,
    )

    enums = signals_contract()["enums"]
    assert list(SIGNAL_TYPES) == enums["signal_types"]
    assert list(SIGNAL_SENIORITY) == enums["seniority"]
    assert list(SIGNAL_COMPANY_SIZES) == enums["company_sizes"]
    assert list(SIGNAL_TYPE_LABELS.items()) == list(signals_contract()["type_labels"].items())


@signals_contract_present
def test_signals_enum_lists_check_the_contract_options():
    """The values the tool accepts for an enum list are the contract's, in order."""
    from jobo_client.service import _SIGNAL_LISTS

    allowed = {name: values for name, _, values in _SIGNAL_LISTS if values is not None}
    by_key = {d["key"]: d for d in signals_contract()["filters"]}
    enum_keys = {k for k, d in by_key.items() if d["kind"] == "enumList"}
    assert set(allowed) == enum_keys - set(SIGNALS_LEFT_OUT)
    for key, values in allowed.items():
        assert list(values) == by_key[key]["options"], key


@signals_contract_present
def test_signals_enum_parameters_name_every_contract_option():
    """The model only learns a closed list's values from the description."""
    parameters = signals_tool_parameters()
    for descriptor in signals_contract()["filters"]:
        if descriptor["kind"] != "enumList" or descriptor["key"] in SIGNALS_LEFT_OUT:
            continue
        description = parameters[descriptor["key"]]["llm_description"]
        missing = [o for o in descriptor["options"] if o not in description]
        assert missing == [], descriptor["key"]


@signals_contract_present
def test_signals_kinds_match_the_tool_parameters():
    """A number filter is a number field, a boolean a switch, the rest strings."""
    expected_type = {"number": "number", "boolean": "boolean"}
    parameters = signals_tool_parameters()
    for descriptor in signals_contract()["filters"]:
        if descriptor["key"] in SIGNALS_LEFT_OUT:
            continue
        parameter = parameters[descriptor["key"]]
        assert parameter["type"] == expected_type.get(descriptor["kind"], "string"), descriptor["key"]
        if descriptor["kind"] == "number":
            assert parameter["min"] == descriptor["min"], descriptor["key"]
            assert parameter["max"] == descriptor["max"], descriptor["key"]


@signals_contract_present
def test_every_signals_filter_reaches_the_query():
    """A parameter that validates but is never sent would be a silent no-op."""
    service = JoboService(JoboClient("jbe_test_drift"))
    baseline = service.signals_request({})
    unsent = []
    for descriptor in signals_contract()["filters"]:
        if descriptor["key"] in SIGNALS_LEFT_OUT:
            continue
        path, params, _ = service.signals_request(
            {descriptor["key"]: signals_sample(descriptor)}
        )
        if (path, params) == baseline[:2] or descriptor["key"] not in params:
            unsent.append(descriptor["key"])
    assert unsent == []


@signals_contract_present
def test_company_mode_takes_exactly_the_contract_company_filters():
    from jobo_client.service import COMPANY_SIGNAL_FILTERS, ToolInputError

    contract = signals_contract()
    assert list(COMPANY_SIGNAL_FILTERS) == contract["company_filter_keys"]

    service = JoboService(JoboClient("jbe_test_drift"))
    company = "0f8e2a52-3c1d-4b7e-9a10-5d6c7b8a9e01"
    for descriptor in contract["filters"]:
        key = descriptor["key"]
        if key in SIGNALS_LEFT_OUT:
            continue
        args = {"company_id": company, key: signals_sample(descriptor)}
        if descriptor.get("company"):
            path, params, _ = service.signals_request(args)
            assert path == f"/api/companies/{company}/signals", key
            assert key in params, key
        else:
            with pytest.raises(ToolInputError, match=f"Remove {key}"):
                service.signals_request(args)


@signals_contract_present
def test_signal_limits_stay_inside_the_contract():
    from jobo_client.service import MAX_SIGNAL_LIMIT, SIGNAL_MAX_LIST_VALUES

    limits = signals_contract()["limits"]
    assert 1 <= MAX_SIGNAL_LIMIT <= limits["max_limit"]
    assert SIGNAL_MAX_LIST_VALUES == limits["max_list_values"]
