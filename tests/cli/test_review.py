"""Tests for `bi2 review`: the review page, its server, and the checks it saves."""

import http.client
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from bi2.cli.main import app
from bi2.cli.review.server import ReviewServer
from bi2.cli.review.session import ReviewSession
from bi2.core.models import Evidence, LogoCandidate
from bi2.core.urls import site_folder
from bi2.evaluation.gold import GoldSite, site_key
from bi2.evaluation.verifications import load_verifications
from bi2.pipeline import failed_result
from bi2.resolvers.cascade import not_built_yet
from tests.factories import answered, site_result

URL = "https://example-cafe.ca/"
DOWN = "https://down.example/"
GOLD = {
    site_key(URL): GoldSite(url=URL, category="cafe", company_names=("Example Cafe",)),
}

runner = CliRunner()


def _run(tmp_path: Path) -> Path:
    """A run's results folder, as `bi2 analyze` leaves it: one site answered, one failed."""
    out = tmp_path / "run"
    folder = out / site_folder(URL)
    folder.mkdir(parents=True)
    result = site_result(
        URL,
        company_name=answered("Example Cafe"),
        logo=answered({"url": f"{URL}logo.png", "image_file": f"{site_folder(URL)}/logo.png"}),
        phone=answered("+14165550199", confidence=0.6, status="needs_review"),
        email=answered("hello@example-cafe.ca"),
        mcc=not_built_yet().model_dump(),
        address=not_built_yet().model_dump(),
    )
    failed = failed_result(DOWN, "the page didn't load", 1.0)
    lines = [result.model_dump_json(), failed.model_dump_json()]
    (out / "results.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    evidence = Evidence(
        page=result.page,
        screenshot_file=f"{site_folder(URL)}/screenshot.jpg",
        logo_candidates=(
            LogoCandidate(number=1, kind="img", url=f"{URL}logo.png"),
            LogoCandidate(number=2, kind="img", url=f"{URL}brand.svg"),
        ),
    )
    (folder / "evidence.json").write_text(evidence.model_dump_json(), encoding="utf-8")
    (folder / "screenshot.jpg").write_bytes(b"\xff\xd8\xff")
    (folder / "logo.png").write_bytes(b"\x89PNG")
    (tmp_path / "secret.png").write_bytes(b"not for the page")
    return out


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ReviewServer]:
    session = ReviewSession(_run(tmp_path), GOLD, tmp_path / "checks.jsonl")
    served = ReviewServer(session)
    thread = threading.Thread(target=served.serve_forever, daemon=True)
    thread.start()
    yield served
    served.shutdown()
    served.server_close()


def _request(
    server: ReviewServer, method: str, path: str, body: Any = None, **headers: str
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    data = json.dumps(body).encode() if body is not None else None
    connection.request(method, path, body=data, headers=headers)
    response = connection.getresponse()
    answer = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return answer


def _check(server: ReviewServer, **fields: str) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json", "X-Review-Token": server.token}
    status, _, body = _request(server, "POST", "/checks", fields, **headers)
    return status, json.loads(body)


def test_every_answer_that_can_be_checked_gets_a_check(server: ReviewServer) -> None:
    status, headers, body = _request(server, "GET", "/")
    page = body.decode()
    assert status == 200
    cells = re.findall(r'<td class="check" data-site="([^"]+)" data-field="(\w+)"', page)
    # Not the fields that aren't built yet, and nothing on the site that failed.
    assert [field for _, field in cells] == [
        "company_name",
        "logo",
        "phone",
        "email",
        "social_links",
    ]
    assert {site for site, _ in cells} == {URL}
    assert "Gold set: right" in page  # the gold set already checks the name
    # Where v2 found nothing, the question is whether there's anything to find.
    assert ">The site has none</button>" in page
    assert ">Missed it</button>" in page
    assert "1 of 5 answers checked" in page
    # Only the page's own scripts may run.
    nonce = re.search(r"script-src 'nonce-([^']+)'", headers["Content-Security-Policy"])
    assert nonce is not None
    assert page.count(f'<script nonce="{nonce[1]}"') == 2
    assert f'data-token="{server.token}"' in page


def test_a_check_is_saved_with_its_note_and_the_page_learns_from_it(
    server: ReviewServer, tmp_path: Path
) -> None:
    status, update = _check(
        server, site=URL, field="phone", verdict="right", note="  It's on their contact page "
    )
    assert status == 200
    phone = next(answer for answer in update["answers"] if answer["field"] == "phone")
    assert (phone["by"], phone["verdict"]) == ("you", "right")
    assert "You: right" in phone["label"]
    assert "sent on, right" in phone["label"]  # it needed review, but it was right
    assert "2 of 5 answers checked: 1 by you" in update["summary"]
    assert "It&#x27;s on their contact page" in update["summary"]
    [saved] = load_verifications(tmp_path / "checks.jsonl").values()
    assert (saved.answer, saved.shown, saved.note) == (
        "+14165550199",
        "+14165550199",
        "It's on their contact page",
    )
    assert (saved.status.value, saved.confidence) == ("needs_review", 0.6)
    # Your check wins over the gold set's, and the page remembers it.
    _check(server, site=URL, field="company_name", verdict="wrong", note="that's the old name")
    page = _request(server, "GET", "/")[2].decode()
    assert 'data-verdict="wrong" aria-pressed="true"' in page
    assert 'value="that&#x27;s the old name"' in page
    assert "kept, wrong" in page
    update = _check(server, site=URL, field="social_links", verdict="wrong")[1]
    social = next(answer for answer in update["answers"] if answer["field"] == "social_links")
    assert "You: missed it" in social["label"]


def test_a_wrong_answer_can_be_given_the_right_one(server: ReviewServer) -> None:
    def correct(field: str, given: str) -> str:
        status, update = _check(server, site=URL, field=field, verdict="wrong", correct=given)
        assert status == 200, update
        return str(next(a for a in update["answers"] if a["field"] == field)["correct"])

    assert correct("phone", "416-555-0123") == "+14165550123"  # written the standard way
    assert correct("logo", "#2") == f"{URL}brand.svg"  # a candidate's number gives its address
    assert correct("email", "Hello@Example-Cafe.CA") == "hello@example-cafe.ca"
    page = _request(server, "GET", "/")[2].decode()
    assert 'class="correct" type="text" maxlength="2000" value="+14165550123"' in page
    assert ">+14165550123<" in page  # in the summary's notes
    for field, given, problem in (
        ("phone", "call us", "isn't a phone number"),
        ("logo", "#9", "no logo candidate #9"),
        ("social_links", "instagram", "full addresses"),
        ("email", "hello at example-cafe.ca", "isn't an email address"),
    ):
        status, update = _check(server, site=URL, field=field, verdict="wrong", correct=given)
        assert (status, problem in update["error"]) == (400, True)


def test_only_the_page_it_served_can_save_checks(server: ReviewServer, tmp_path: Path) -> None:
    check = {"site": URL, "field": "phone", "verdict": "right"}
    json_only = {"Content-Type": "application/json"}
    assert _request(server, "POST", "/checks", check, **json_only)[0] == 403  # no token
    wrong_host = {**json_only, "X-Review-Token": server.token, "Host": "evil.example"}
    assert _request(server, "POST", "/checks", check, **wrong_host)[0] == 403
    assert _request(server, "GET", "/", Host="evil.example")[0] == 403
    assert _check(server, site=URL, field="mcc", verdict="right")[0] == 404  # not built yet
    assert _check(server, site=DOWN, field="phone", verdict="right")[0] == 404  # failed
    assert _check(server, site=URL, field="phone", verdict="maybe")[0] == 400
    assert not (tmp_path / "checks.jsonl").exists()


def test_only_pictures_in_the_results_folder_are_served(server: ReviewServer) -> None:
    status, headers, body = _request(server, "GET", "/example-cafe.ca/screenshot.jpg")
    assert (status, headers["Content-Type"], body) == (200, "image/jpeg", b"\xff\xd8\xff")
    assert headers["Content-Security-Policy"].startswith("sandbox")
    assert _request(server, "GET", "/results.jsonl")[0] == 404  # not a picture
    assert _request(server, "GET", "/../secret.png")[0] == 404
    assert _request(server, "GET", "/%2e%2e/secret.png")[0] == 404


def test_review_starts_the_server_and_says_where(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ReviewServer, "serve_forever", lambda self: None)
    outcome = runner.invoke(
        app,
        [
            "review",
            str(_run(tmp_path)),
            "--gold",
            str(tmp_path / "no-gold.toml"),
            "--checks",
            str(tmp_path / "checks.jsonl"),
            "--no-open",
        ],
    )
    assert outcome.exit_code == 0, outcome.output
    assert "Reviewing 2 sites" in outcome.output
    assert "Checked so far: 0 of 5 answers, 0 by you" in outcome.output  # no gold set
    assert "Review page: http://127.0.0.1:" in outcome.output


def test_review_needs_a_run(tmp_path: Path) -> None:
    outcome = runner.invoke(app, ["review", str(tmp_path), "--no-open"])
    assert outcome.exit_code == 1
    assert "run `bi2 analyze` first" in outcome.output
