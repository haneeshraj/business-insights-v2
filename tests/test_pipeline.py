"""Tests for the per-site workflow, with stand-ins for the browser, downloads and files."""

from bi2.core.models import Box, RenderedImage, Status
from bi2.pipeline import analyze_snapshot, analyze_url
from tests.factories import page_snapshot
from tests.fakes import MemoryFiles, fake_context
from tests.resolvers.images import picture, screenshot_with_logo

URL = "https://example-cafe.ca/"
PAGE = """<html><head><title>Example Cafe | Coffee in Toronto</title>
<meta property="og:site_name" content="Example Cafe">
<script type="application/ld+json">
  {"@type": "CafeOrCoffeeShop", "name": "Example Cafe", "telephone": "+1 416-555-0123"}
</script></head>
<body><header><a href="/"><img src="/logo.png" alt="Example Cafe logo"></a></header>
<main><p>Coffee and pastries.</p></main>
<footer><a href="tel:+14165550123">Call us</a> <a href="https://instagram.com/examplecafe">Instagram</a></footer>
</body></html>"""
LOGO = RenderedImage(
    kind="img",
    url=f"{URL}logo.png",
    alt="Example Cafe logo",
    box=Box(x=20, y=10, width=160, height=60),
    in_header=True,
    links_home=True,
)


async def test_a_page_is_analyzed_into_a_result_with_its_files_saved() -> None:
    files = MemoryFiles()
    snapshot = page_snapshot(PAGE, images=(LOGO,), screenshot=screenshot_with_logo(20, 10, 160, 60))
    ctx = fake_context(downloads={f"{URL}logo.png": picture(160, 60)}, files=files)
    result, ev = await analyze_snapshot(snapshot, ctx)
    statuses = {name: field.status for name, field in result.field_results.items()}
    assert statuses == {
        "company_name": Status.OK,
        "logo": Status.OK,
        "mcc": Status.NOT_FOUND,
        "address": Status.NOT_FOUND,
        "phone": Status.OK,
        "social_links": Status.OK,
    }
    assert result.company_name.value == "Example Cafe"
    assert result.phone.value == "+14165550123"
    assert result.mcc.steps[0].detail == "this field isn't built yet"
    assert ev.screenshot_file == "example-cafe.ca/screenshot.jpg"
    folder = {path for path in files.files if path.startswith("example-cafe.ca/")}
    assert folder == {
        "example-cafe.ca/screenshot.jpg",
        "example-cafe.ca/logo.png",
        "example-cafe.ca/evidence.json",
        "example-cafe.ca/result.json",
    }
    assert set(result.versions.data) == {"countries", "platforms"}


async def test_the_logo_comes_from_the_browsers_copy_when_a_download_is_refused() -> None:
    files = MemoryFiles()
    snapshot = page_snapshot(
        PAGE,
        images=(LOGO,),
        screenshot=screenshot_with_logo(20, 10, 160, 60),
        image_copies={f"{URL}logo.png": picture(160, 60)},
    )
    result, _ = await analyze_snapshot(snapshot, fake_context(files=files))  # no downloads
    assert result.logo.status is Status.OK
    assert "example-cafe.ca/logo.png" in files.files


async def test_a_page_that_wont_load_fails_every_field_and_says_why() -> None:
    result, ev = await analyze_url(URL, fake_context())
    assert ev is None
    assert result.error == f"couldn't load {URL}"
    assert {field.status for field in result.field_results.values()} == {Status.ERROR}
