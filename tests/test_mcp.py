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
