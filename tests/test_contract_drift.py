"""
Drift guard against the shared connector filter contract.

`Jobo.Connectors/contracts/filters.json` is generated from the connector core
and lists every search filter the Jobo connectors support. These tests fail
when the contract gains a filter search_jobs does not take or does not send,
or when an enum here stops matching it.

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
