"""The plugin's own files agree with each other and with the Marketplace rules."""

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ["search_jobs", "get_job", "find_companies", "find_filter_values", "find_locations"]


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def test_manifest_lists_the_provider():
    manifest = load("manifest.yaml")
    assert manifest["author"] == "jobo" and manifest["name"] == "jobo"
    assert manifest["plugins"]["tools"] == ["provider/jobo.yaml"]
    assert manifest["privacy"] == "./PRIVACY.md" and (ROOT / "PRIVACY.md").is_file()
    assert (ROOT / manifest["icon"].replace("icon.svg", "_assets/icon.svg")).is_file()


def test_manifest_has_no_field_the_dify_schema_lacks():
    # Dify's manifest has no egress allowlist: a `network` block would be
    # ignored, and claiming it limits the plugin's traffic would be false.
    assert "network" not in load("manifest.yaml")


def test_provider_lists_every_tool_and_one_secret():
    provider = load("provider/jobo.yaml")
    assert provider["tools"] == [f"tools/{name}.yaml" for name in TOOLS]
    assert list(provider["credentials_for_provider"]) == ["jobo_api_key"]
    assert provider["credentials_for_provider"]["jobo_api_key"]["type"] == "secret-input"


def test_every_tool_has_english_descriptions_and_a_python_source():
    for name in TOOLS:
        tool = load(f"tools/{name}.yaml")
        assert tool["identity"]["name"] == name
        assert tool["description"]["human"]["en_US"] and tool["description"]["llm"]
        assert (ROOT / tool["extra"]["python"]["source"]).is_file()
        for parameter in tool["parameters"]:
            assert parameter["human_description"]["en_US"], (name, parameter["name"])
            assert parameter["llm_description"], (name, parameter["name"])


def test_billing_statements_match_the_billing_docs():
    search = load("tools/search_jobs.yaml")["description"]
    assert "billed per job returned" in search["human"]["en_US"].lower()
    assert "BILLED per job returned" in search["llm"]
    for name in TOOLS[1:]:
        text = load(f"tools/{name}.yaml")["description"]["llm"]
        assert "Free: not billed" in text, name
    # A price may only be stated where docs/billing.mdx states it; tools state none.
    for name in TOOLS:
        assert "$" not in yaml.safe_dump(load(f"tools/{name}.yaml")), name


def test_page_size_default_and_cap_in_the_schema():
    page_size = next(
        p for p in load("tools/search_jobs.yaml")["parameters"] if p["name"] == "page_size"
    )
    assert page_size["default"] == 5 and page_size["max"] == 25


def test_dependencies_are_pinned_and_dify_plugin_is_recent_enough():
    lines = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert any(line.lower().startswith("dify_plugin==0.1") for line in lines)
    assert all(line.count("==") == 1 for line in lines)
    assert not any("git+" in line or "://" in line for line in lines)


def test_python_sources_compile_and_hold_no_key_like_string():
    for path in ROOT.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        ast.parse(source)
        assert "jbe_live_" not in source, path
