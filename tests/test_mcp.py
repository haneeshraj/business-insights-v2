"""Tests for the MCP server's tools that need no browser or model."""

import json

import pytest

pytest.importorskip("mcp")

from bi2.mcp.server import find_mcc, mcp


async def test_the_server_offers_its_tools() -> None:
    names = {tool.name for tool in await mcp.list_tools()}
    assert names == {"analyze_website", "explain_field", "find_mcc", "model_usage"}


def test_codes_are_found_by_words_or_by_number() -> None:
    assert json.loads(find_mcc("5813")) == {"5813": find_mcc_description("5813")}
    found = json.loads(find_mcc("book stores"))
    assert "5942" in found


def find_mcc_description(code: str) -> str:
    from bi2.resolvers.mcc import mcc_codes

    return mcc_codes()[code]


async def test_analyze_website_returns_every_field_and_explain_reads_its_steps() -> None:
    from types import SimpleNamespace

    from bi2.adapters.local.answers import CallLog
    from bi2.mcp.server import _State, analyze_website, explain_field
    from tests.factories import page_snapshot
    from tests.fakes import fake_context

    page = page_snapshot(
        '<title>Example Cafe</title><meta property="og:site_name" content="Example Cafe">',
        url="https://example-cafe.ca/",
    )
    state = _State(ctx=fake_context(pages={page.url: page}), log=CallLog(None), results={})
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=state))
    summary = json.loads(await analyze_website("example-cafe.ca", context))  # type: ignore[arg-type]
    assert summary["url"] == "https://example-cafe.ca/"
    assert summary["fields"]["company_name"]["value"] == "Example Cafe"
    assert set(summary["fields"]) == {
        "company_name", "logo", "mcc", "address", "phone", "email", "social_links",
    }  # fmt: skip
    steps = json.loads(await explain_field("example-cafe.ca", "mcc", context))  # type: ignore[arg-type]
    assert steps["steps"][0]["step"] == "mcc_by_decider"
