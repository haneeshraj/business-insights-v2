"""What every provider's client shares: images as models take them, reading a JSON answer out of
a reply's text, and how long to wait when a provider asks for a pause."""

import json
from typing import Any, Final

import httpx

from bi2.core.errors import ModelUnavailable

BUSY: Final = frozenset({500, 502, 503, 504, 529})  # 529 is Anthropic's "overloaded"
TRIES: Final = 3
LONGEST_WAIT_S: Final = 60.0


def media_type(image: bytes) -> str:
    """An image's media type, from its first bytes: PNG or JPEG, the two every model takes."""
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8"):
        return "image/jpeg"
    raise ValueError("only PNG and JPEG images can be sent to a model")


def json_part(text: str) -> str:
    """The JSON object in an answer's text, without the code fence or words around it."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text


def json_answer(text: str, model: str) -> dict[str, Any]:
    """The JSON object a reply's text holds. Raises ModelUnavailable when there isn't one."""
    try:
        answer = json.loads(json_part(text))
    except ValueError as exc:
        raise ModelUnavailable(f"{model}'s answer wasn't JSON") from exc
    if not isinstance(answer, dict):
        raise ModelUnavailable(f"{model}'s answer wasn't a JSON object")
    return answer


def with_schema(instructions: str, schema: dict[str, Any]) -> str:
    """Instructions that ask for the schema's JSON in words, for a provider that can't be given
    the schema itself."""
    return f"{instructions}\n\nAnswer with only a JSON object matching this schema: {json.dumps(schema)}"


def retry_after(response: httpx.Response, attempt: int) -> float:
    """How long to wait before asking again: what the provider asks, or a doubling pause."""
    for header in ("retry-after", "x-ratelimit-reset-requests"):
        value = response.headers.get(header, "").strip().rstrip("s")
        try:
            return min(float(value), LONGEST_WAIT_S)
        except ValueError:
            continue
    return min(2.0 * 2.0**attempt, LONGEST_WAIT_S)


def error_message(response: httpx.Response) -> str:
    """The message in an error response, as the provider wrote it."""
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    error = data.get("error", data) if isinstance(data, dict) else data
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or error)[:300]
    return str(error)[:300]
