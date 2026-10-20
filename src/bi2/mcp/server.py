"""The MCP server's tools: analyze a website, explain how a field was decided, and look up
merchant category codes.

One browser and one set of model clients stay open for the server's lifetime, so each request
only loads its page. Results and the model answers behind them are kept in v2's own folder, so
asking about the same site twice asks no model twice.
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from mcp.server.mcpserver import Context, MCPServer

from bi2.adapters.local.answers import CallLog
from bi2.core.context import RunContext
from bi2.core.models import FIELD_NAMES, SiteResult
from bi2.core.text import fold
from bi2.pipeline import analyze_url
from bi2.resolvers.mcc import mcc_codes
from bi2.wiring import local_context


@dataclass
class _State:
    ctx: RunContext
    log: CallLog
    results: dict[str, SiteResult]


def _folder() -> Path:
    return Path(typer.get_app_dir("bi2"))


@asynccontextmanager
async def _lifespan(server: MCPServer[Any]) -> AsyncIterator[_State]:
    folder = _folder()
    log = CallLog(folder / "mcp" / "model-calls.jsonl")
    async with local_context(
        folder / "mcp" / "results",
        kept_answers=folder / "answers",
        usage_file=folder / "free-tier-usage.json",
        call_log=log,
    ) as ctx:
        yield _State(ctx=ctx, log=log, results={})


mcp: MCPServer[_State] = MCPServer(
    "business-insights",
    instructions=(
        "Business Insights v2 finds a business's name, logo, merchant category code (MCC), "
        "head-office address with map coordinates, phone, email and social links from its "
        "website. Every field comes with a status (ok, needs_review, not_found, error), a "
        "confidence and its source. Treat needs_review answers as unconfirmed."
    ),
    lifespan=_lifespan,
)


def _state(context: Context[Any, Any]) -> _State:
    state: _State = context.request_context.lifespan_context
    return state


def _summary(result: SiteResult) -> dict[str, Any]:
    """A result as the assistant reads it: each field's value, status, confidence and source."""
    fields = {
        name: {
            "value": field.model_dump(mode="json")["value"],
            "status": field.status.value,
            "confidence": field.confidence,
            "source": field.source,
        }
        for name, field in result.field_results.items()
    }
    return {
        "url": result.page.url,
        "page_kind": result.page.kind.value,
        "platform": result.page.platform,
        "error": result.error,
        "seconds": result.seconds,
        "cost_usd_at_list_price": str(result.cost.usd),
        "fields": fields,
    }


@mcp.tool()
async def analyze_website(url: str, context: Context[Any, Any]) -> str:
    """Analyze a business's website and return its name, logo, MCC, address with
    coordinates, phone, email and social links, each with its status, confidence and source.
    Takes 5 to 60 seconds: it loads the page in a browser, then asks models only about the
    answers its rules aren't sure of."""
    state = _state(context)
    if "://" not in url:
        url = f"https://{url}"
    result, _ = await analyze_url(url, state.ctx)
    state.results[url] = result
    return json.dumps(_summary(result), indent=2)


@mcp.tool()
async def explain_field(url: str, field: str, context: Context[Any, Any]) -> str:
    """Explain how one field of a website analyzed earlier was decided: every step that ran,
    why each passed to the next, and what its model calls cost. Fields: company_name, logo,
    mcc, address, phone, email, social_links."""
    if field not in FIELD_NAMES:
        return f"unknown field {field}; the fields are {', '.join(FIELD_NAMES)}"
    state = _state(context)
    if "://" not in url:
        url = f"https://{url}"
    result = state.results.get(url)
    if result is None:
        return f"{url} hasn't been analyzed in this session; call analyze_website first"
    answer = result.field_results[field]
    steps = [
        {
            "step": step.step,
            "outcome": step.outcome.value,
            "detail": step.detail,
            "confidence": step.confidence,
            "cost_usd": str(step.cost.usd),
        }
        for step in answer.steps
    ]
    return json.dumps({"field": field, "evidence": list(answer.evidence), "steps": steps}, indent=2)


@mcp.tool()
def find_mcc(words: str) -> str:
    """Find merchant category codes whose official description contains all the given words,
    like "eating places" or "book stores". Also takes a code, like 5813."""
    codes = mcc_codes()
    if words.strip().isdigit():
        code = words.strip().zfill(4)
        return json.dumps({code: codes.get(code, "no such code")})
    wanted = fold(words).split()
    found = {code: text for code, text in codes.items() if all(w in fold(text) for w in wanted)}
    return json.dumps(dict(list(found.items())[:25]) or {"found": "no code matches"}, indent=2)


@mcp.tool()
def model_usage(context: Context[Any, Any]) -> str:
    """What this session has asked models so far, and what it would cost at list price."""
    log = _state(context).log
    spent = log.spent
    return json.dumps(
        {
            "model_calls": log.calls,
            "answered_from_kept_answers": log.kept,
            "failed": log.failed,
            "input_tokens": spent.input_tokens,
            "output_tokens": spent.output_tokens,
            "usd_at_list_price": str(spent.usd),
        },
        indent=2,
    )


def serve() -> None:
    """Run the server over standard input and output, the way MCP clients start servers."""
    mcp.run()
