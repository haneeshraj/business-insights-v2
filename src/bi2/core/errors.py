"""v2's own exception types. Code raises these, and only the cascade and the pipeline turn
them into field statuses."""


class Bi2Error(Exception):
    """Base class for v2's own errors."""


class FetchError(Bi2Error):
    """A page couldn't be loaded."""


class UnsafeUrl(FetchError):
    """The URL points somewhere v2 refuses to go, such as a private network."""


class PageTimeout(FetchError):
    """A page didn't load in time."""


class WrongCertificateName(FetchError):
    """The site's security certificate is for another of its names, such as the one without
    "www.", so no browser loads the page under this one."""


class BrowserUnavailable(Bi2Error):
    """No browser could be started."""


class LookupUnavailable(Bi2Error):
    """A knowledge base, like Wikidata, couldn't be reached."""
