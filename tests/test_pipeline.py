"""Tests for the per-site workflow, with stand-ins for the browser, downloads and files."""

from bi2.core.models import Box, KnownBusiness, RenderedImage, Status
from bi2.pipeline import analyze_snapshot, analyze_url
from tests.factories import page_snapshot
from tests.fakes import FakeKnowledge, MemoryFiles, fake_context
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
        "email": Status.NOT_FOUND,  # the page shows no address, and links no contact page
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


CONTACT = f"{URL}contact-us"
HOME = """<html><head><title>Example Cafe</title></head>
<body><header><a href="/contact-us">Contact us</a></header><main>Coffee.</main></body></html>"""
CONTACT_PAGE = """<html><body><footer>Call us at (416) 555-0123 or write to
<a href="mailto:hello@example-cafe.ca">hello@example-cafe.ca</a></footer></body></html>"""


async def test_the_contact_page_is_read_when_the_homepage_shows_no_phone_or_email() -> None:
    pages = {CONTACT: page_snapshot(CONTACT_PAGE, url=CONTACT)}
    result, ev = await analyze_snapshot(page_snapshot(HOME), fake_context(pages=pages))
    assert ev.extra_pages == (CONTACT,)
    assert (result.phone.value, result.phone.source) == ("+14165550123", "contact page: footer")
    assert (result.email.value, result.email.status) == ("hello@example-cafe.ca", Status.OK)


async def test_the_contact_page_is_read_when_the_homepage_only_shows_a_jobs_address() -> None:
    home = HOME.replace(
        "<main>Coffee.</main>",
        "<main>Coffee. Call (416) 555-0123. Jobs: careers@example-cafe.ca</main>",
    )
    pages = {CONTACT: page_snapshot(CONTACT_PAGE, url=CONTACT)}
    result, ev = await analyze_snapshot(page_snapshot(home), fake_context(pages=pages))
    assert ev.extra_pages == (CONTACT,)
    assert (result.email.value, result.email.source) == (
        "hello@example-cafe.ca",
        "contact page: email link + footer",
    )


async def test_a_contact_page_that_wont_load_leaves_the_homepage_to_stand_alone() -> None:
    result, ev = await analyze_snapshot(page_snapshot(HOME), fake_context())  # nothing to load
    assert ev.contact_page is None
    assert result.phone.status is Status.NOT_FOUND
    assert result.phone.steps[-1].detail == "no contact page was read"


NO_FRILLS_URL = "https://www.nofrills.ca/"


async def test_a_page_that_wont_load_is_answered_from_what_wikidata_knows() -> None:
    known = KnownBusiness(item="Q3342407", name="No Frills", phone="+1 866-987-6453")
    ctx = fake_context(knowledge=FakeKnowledge({"nofrills.ca": known}))
    result, ev = await analyze_url(NO_FRILLS_URL, ctx)  # the fake fetcher has no pages
    assert result.error is None
    assert ev is not None
    assert ev.unreadable
    assert (result.company_name.value, result.company_name.status) == ("No Frills", Status.OK)
    assert result.phone.status is Status.NEEDS_REVIEW
    # What Wikidata doesn't know stays an error that says why the page couldn't be read.
    assert result.logo.status is Status.ERROR
    assert result.logo.steps[0].step == "load_page"


async def test_a_page_that_wont_load_and_isnt_known_fails_as_a_whole() -> None:
    result, ev = await analyze_url(NO_FRILLS_URL, fake_context(knowledge=FakeKnowledge()))
    assert result.error is not None
    assert ev is None


async def test_a_refused_page_is_looked_up_rather_than_read() -> None:
    known = FakeKnowledge({"nofrills.ca": KnownBusiness(item="Q3342407", name="No Frills")})
    snapshot = page_snapshot("<title>Access Denied</title>", url=NO_FRILLS_URL, status_code=403)
    result, ev = await analyze_snapshot(snapshot, fake_context(knowledge=known))
    assert result.company_name.value == "No Frills"
    assert "refused the page (403)" in (ev.unreadable or "")
