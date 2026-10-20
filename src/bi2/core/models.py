"""The data types every part of v2 passes around.

Every model is immutable and rejects unknown keys, so a misspelled key fails loudly instead of
silently dropping data. Results also check their own rules: a field that wasn't answered can
never carry a guessed value.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

# Version of the SiteResult JSON format. A breaking change bumps the major version.
SCHEMA_VERSION: Final = "2.0"

# The fields every SiteResult reports, in output order.
FIELD_NAMES: Final = (
    "company_name",
    "logo",
    "mcc",
    "address",
    "phone",
    "email",
    "social_links",
)


def _require_web_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        # Also rejects placeholders such as `data:image/gif;base64,...`, which lazy-loading
        # pages put where the real image URL should be.
        raise ValueError("must be an http or https URL")
    return value


WebUrl = Annotated[str, AfterValidator(_require_web_url)]
CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]  # ISO 3166-1, e.g. "CA"
MccCode = Annotated[str, StringConstraints(pattern=r"^\d{4}$")]  # text, so "0742" keeps its zero
PhoneNumber = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{6,14}$")]  # E.164
EmailAddress = Annotated[str, StringConstraints(pattern=r"^[^@\s]+@[^@\s]+\.[a-z]{2,24}$")]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class _Frozen(BaseModel):
    """Base for every model here: immutable, and strict about unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- How fields are decided --------------------------------------------------


class Status(StrEnum):
    """How a field ended up. No field is ever given a guessed default."""

    OK = "ok"
    NEEDS_REVIEW = "needs_review"  # has a best answer, but below the confidence threshold
    NOT_FOUND = "not_found"  # no source had an answer
    ERROR = "error"  # a fetch or provider failure stopped every step


class Cost(_Frozen):
    """Money and tokens spent on model calls."""

    usd: Decimal = Field(default=Decimal(0), ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)

    def __add__(self, other: "Cost") -> "Cost":
        return Cost(
            usd=self.usd + other.usd,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            model_calls=self.model_calls + other.model_calls,
        )


class StepOutcome(StrEnum):
    """What happened at one step of a field's cascade."""

    RESOLVED = "resolved"  # answered confidently enough to stop
    ESCALATED = "escalated"  # no confident answer, so the next step ran
    FAILED = "failed"  # a fetch or provider error


class StepRecord(_Frozen):
    """One step of a field's cascade. Together, the steps are the field's audit trail."""

    step: str = Field(min_length=1)  # for example "free_sources", "decider" or "llm"
    outcome: StepOutcome
    detail: str = ""  # why the step escalated or failed
    confidence: Confidence | None = None
    cost: Cost = Field(default_factory=Cost)


class FieldResult[T](_Frozen):
    """One output field: the answer, how sure we are, where it came from, how it was decided."""

    value: T | None = None
    status: Status
    confidence: Confidence | None = None
    source: str | None = None  # for example "structured data + page title", or "analyst"
    evidence: tuple[str, ...] = ()  # quotes or URLs that support the value
    steps: tuple[StepRecord, ...] = ()

    @model_validator(mode="after")
    def _value_matches_status(self) -> Self:
        answered = self.status in (Status.OK, Status.NEEDS_REVIEW)
        if answered and (self.value is None or self.confidence is None or not self.source):
            raise ValueError(
                f"a field marked {self.status} needs a value, a confidence and a source"
            )
        if not answered and (self.value is not None or self.confidence is not None):
            raise ValueError(
                f"a field marked {self.status} can't carry a value or confidence, not even a guess"
            )
        return self

    @property
    def cost(self) -> Cost:
        """Everything spent deciding this field."""
        return sum((step.cost for step in self.steps), Cost())


# --- Field values ------------------------------------------------------------


class Logo(_Frozen):
    """The business's logo."""

    url: WebUrl | None = None  # None when the logo is an inline SVG or a CSS image
    image_file: str | None = None  # saved copy, relative to the results folder
    icon_url: WebUrl | None = None  # the square app icon, for enrichment use
    # The logo's own colors, as "#rrggbb", the most used first, leaving out its background.
    colors: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _has_an_image(self) -> Self:
        if self.url is None and self.image_file is None:
            raise ValueError("a logo needs a URL or a saved image file")
        return self


class Mcc(_Frozen):
    """A merchant category code and its official description."""

    code: MccCode
    description: str = Field(min_length=1)


class Coordinates(_Frozen):
    """A point on the map."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Address(_Frozen):
    """A business address, kept the way the business published it."""

    text: str = Field(min_length=1)  # exactly as published
    street: str | None = None
    city: str | None = None
    region: str | None = None  # state, province or county
    postal_code: str | None = None
    country: CountryCode | None = None
    coordinates: Coordinates | None = None
    geocode_agrees: bool | None = None  # False when geocoding matched another street or postcode
    multiple_locations: bool = False  # the business has more than one location


class GeocodedPlace(_Frozen):
    """Where a map service puts an address, and the parts it gives it."""

    coordinates: Coordinates
    postal_code: str | None = None
    city: str | None = None
    region: str | None = None
    country: CountryCode | None = None
    source: str = ""  # who placed it, and how it names the place


class SocialProfile(_Frozen):
    """One of the business's profiles on a social platform."""

    platform: str = Field(min_length=1)  # for example "instagram"
    url: WebUrl


SocialLinks = Annotated[tuple[SocialProfile, ...], Field(min_length=1)]


# Each field's result type, the same classes everywhere a result is built or read.
NameResult = FieldResult[CompanyName]
LogoResult = FieldResult[Logo]
MccResult = FieldResult[Mcc]
AddressResult = FieldResult[Address]
PhoneResult = FieldResult[PhoneNumber]  # the main number, in E.164 format
EmailResult = FieldResult[EmailAddress]  # the main address, lowercased
SocialResult = FieldResult[SocialLinks]


# --- The page ----------------------------------------------------------------


class PageKind(StrEnum):
    """Whether the URL is the business's own website or its page on another platform."""

    OWN_WEBSITE = "own_website"
    PLATFORM_PROFILE = "platform_profile"  # for example a cafe's Pinterest or Yelp page
    UNKNOWN = "unknown"  # the page didn't load, or couldn't be classified


class PageInfo(_Frozen):
    """Which page was analyzed, and what kind of page it is."""

    url: WebUrl  # the URL the user gave
    final_url: WebUrl | None = None  # after redirects; None when the page didn't load
    kind: PageKind = PageKind.UNKNOWN
    platform: str | None = None  # the platform's name, for platform profiles
    profile_name: str | None = None  # the business's name as its profile shows it
    own_website: WebUrl | None = None  # the business's own site, when its profile links to one

    @model_validator(mode="after")
    def _platform_matches_kind(self) -> Self:
        is_profile = self.kind is PageKind.PLATFORM_PROFILE
        if is_profile and not self.platform:
            raise ValueError("a platform profile needs the platform's name")
        profile_only = (self.platform, self.profile_name, self.own_website)
        if not is_profile and any(value is not None for value in profile_only):
            raise ValueError(
                "only platform profiles have a platform, a profile name or a linked own website"
            )
        return self


# --- Evidence: what was collected before any model runs ----------------------


class Box(_Frozen):
    """An element's position and size on the screenshot, in CSS pixels."""

    x: float
    y: float
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class RenderedImage(_Frozen):
    """An image-like element as the browser drew it, before any judgment about what it is."""

    # "text": a link home labeled as the logo with no picture inside, like a logo drawn as
    # styled text, to be cut out of the screenshot.
    kind: Literal["img", "svg", "background", "text"]
    url: str = ""  # the resolved URL; may be a data: placeholder; empty for inline SVG and text
    alt: str = ""  # for SVG, its aria-label or <title>
    css_class: str = ""
    element_id: str = ""
    box: Box | None = None
    in_header: bool = False
    links_home: bool = False  # sits inside a link to the site's home page
    # What the link around it says about it: its label, title, class, id and test ID, like
    # "Mejuri logo - Click to return to the homepage".
    link_label: str = ""
    # For an inline SVG that may be the logo: its code, standalone, with the page's styles
    # written in, so it can be saved as the logo's own file.
    svg: str = ""


class TextRegions(_Frozen):
    """The page's visible text, split by where it appears."""

    header: str = ""
    main: str = ""
    footer: str = ""


class PageSnapshot(_Frozen):
    """What loading a page captured. Evidence is built from this; nothing here is judged yet."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", ser_json_bytes="base64", val_json_bytes="base64"
    )

    url: WebUrl  # the URL that was asked for
    final_url: WebUrl  # after redirects
    status_code: int | None = None
    html: str  # the page after its scripts ran
    images: tuple[RenderedImage, ...] = ()
    text: TextRegions | None = None  # the visible text, when a browser read the page
    screenshot: bytes | None = None  # JPEG of the first screen
    # The browser's own copies of the images likeliest to be the logo, by URL. Some sites refuse
    # a separate download of an image they gave the browser to show the page.
    image_copies: dict[str, bytes] = Field(default_factory=dict)
    fetched_at: AwareDatetime
    loaded_with: str  # the browser that loaded it, like "chromium-shell" or "edge"


class LogoCandidate(_Frozen):
    """An image on the page that might be the logo."""

    number: int = Field(ge=1)  # drawn on the screenshot, so a model can answer "which number?"
    kind: Literal["img", "svg", "background", "text", "structured_data", "icon"]
    url: WebUrl | None = None  # None for inline SVG and text
    alt: str = ""
    css_class: str = ""
    box: Box | None = None  # None for images that aren't drawn on the page
    in_header: bool = False
    links_home: bool = False
    declared: bool = False  # the page's structured data names it as the logo
    points: int = 0  # how logo-like the ranking found it; candidates are numbered by it
    svg: str = ""  # an inline SVG's own code, when the page reader kept it


class PageMeta(_Frozen):
    """The page's title and meta tags."""

    title: str = ""
    description: str = ""
    site_name: str = ""  # og:site_name or the app name; on a platform profile, the platform's
    og_title: str = ""
    og_image: WebUrl | None = None


class StructuredData(_Frozen):
    """What the page's schema.org data says about the business."""

    types: tuple[str, ...] = ()  # schema.org types, for example ("Brewery",)
    name: str | None = None
    legal_name: str | None = None
    logo_url: WebUrl | None = None
    telephone: str | None = None
    email: str | None = None
    address: Address | None = None
    same_as: tuple[WebUrl, ...] = ()  # the business's other profiles, such as social media


class Contacts(_Frozen):
    """Contact details found on the page: in its text, its call and email links, and its
    structured data."""

    phones: tuple[PhoneNumber, ...] = ()
    # Where each number was found: "structured data", "call link", "footer", "header" or
    # "main text".
    phone_places: dict[PhoneNumber, tuple[str, ...]] = Field(default_factory=dict)
    emails: tuple[str, ...] = ()
    # Where each address was found: "structured data", "email link", "footer", "header",
    # "main text", or only "hidden text", which the page doesn't show until it's opened, like
    # an accordion or a dialog.
    email_places: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    postcodes: tuple[str, ...] = ()
    copyright_line: str | None = None  # often names the legal entity


class ContactPage(_Frozen):
    """The site's contact page, read when its homepage doesn't show a phone number, an email
    address and a street address."""

    url: WebUrl
    contacts: Contacts = Field(default_factory=Contacts)
    text: str = ""  # its main text and footer, shortened, where addresses are looked for


class KnownBusiness(_Frozen):
    """What Wikidata, a free public knowledge base, says about the business whose official
    website the site is. Big brands are there; most small businesses aren't."""

    item: str = Field(pattern=r"^Q\d+$")  # its Wikidata ID, like "Q3342407"
    name: str = ""
    logo_url: WebUrl | None = None  # the logo's file on Wikimedia Commons
    phone: str = ""
    email: str = ""
    social_links: tuple[SocialProfile, ...] = ()
    # Its head office's street address, postcode and city, when Wikidata gives them.
    head_office: str = ""
    head_office_postcode: str = ""
    head_office_city: str = ""

    @property
    def source(self) -> str:
        """Where it came from, for an answer's source."""
        return f"Wikidata {self.item}"


class Evidence(_Frozen):
    """Everything collected from a site before any model runs. Models only ever see this."""

    page: PageInfo
    meta: PageMeta = Field(default_factory=PageMeta)
    structured: StructuredData = Field(default_factory=StructuredData)
    logo_candidates: tuple[LogoCandidate, ...] = ()
    text: TextRegions = Field(default_factory=TextRegions)
    contacts: Contacts = Field(default_factory=Contacts)
    social_links: tuple[SocialProfile, ...] = ()  # profiles the page links to or lists
    countries: tuple[CountryCode, ...] = ()  # likely countries, most likely first
    screenshot_file: str | None = None
    contact_pages: tuple[WebUrl, ...] = ()  # the site's own pages likely to hold contact details
    extra_pages: tuple[WebUrl, ...] = ()  # contact and about pages that were also read
    contact_page: ContactPage | None = None  # the contact details on the contact page, if read
    # Why the page couldn't be read, like a bot check, when it couldn't. Its fields then come
    # only from what Wikidata knows about the business, in `known`.
    unreadable: str | None = None
    known: KnownBusiness | None = None

    @model_validator(mode="after")
    def _candidate_numbers_are_unique(self) -> Self:
        numbers = [candidate.number for candidate in self.logo_candidates]
        if len(numbers) != len(set(numbers)):
            raise ValueError("logo candidate numbers must be unique")
        return self


# --- The result for one site -------------------------------------------------


class Versions(_Frozen):
    """The code, prompt and data versions a result was produced with."""

    pipeline: str = Field(min_length=1)
    prompts: dict[str, str] = Field(default_factory=dict)
    data: dict[str, str] = Field(default_factory=dict)


def _not_in_this_result() -> FieldResult[Any]:
    """A field a result was made without, because it wasn't built yet: not found, saying so."""
    record = StepRecord(
        step="not_built_yet",
        outcome=StepOutcome.ESCALATED,
        detail="this field wasn't built when this result was made",
    )
    return FieldResult(status=Status.NOT_FOUND, steps=(record,))


def _never_built(field: FieldResult[Any]) -> bool:
    return bool(field.steps) and field.steps[0].step == "not_built_yet"


class SiteResult(_Frozen):
    """Everything v2 reports about one site. Its JSON form is the output contract."""

    schema_version: Literal["2.0"] = SCHEMA_VERSION
    page: PageInfo
    analyzed_at: AwareDatetime
    seconds: float = Field(ge=0)  # wall-clock time for the whole site
    company_name: NameResult
    logo: LogoResult
    mcc: MccResult
    address: AddressResult
    phone: PhoneResult
    # Results made before the email field was built don't have it.
    email: EmailResult = Field(default_factory=lambda: _not_in_this_result())
    social_links: SocialResult
    error: str | None = None  # why the site couldn't be analyzed at all
    versions: Versions

    @model_validator(mode="after")
    def _site_error_fails_every_field(self) -> Self:
        if self.error is not None:
            not_failed = [
                name
                for name, field in self.field_results.items()
                if field.status is not Status.ERROR and not _never_built(field)
            ]
            if not_failed:
                raise ValueError(f"the site failed, so every field must be an error: {not_failed}")
        return self

    @property
    def field_results(self) -> dict[str, FieldResult[Any]]:
        """Every output field by name, in output order."""
        return {name: getattr(self, name) for name in FIELD_NAMES}

    @property
    def cost(self) -> Cost:
        """Everything spent on this site, summed from each field's steps."""
        return sum((field.cost for field in self.field_results.values()), Cost())
