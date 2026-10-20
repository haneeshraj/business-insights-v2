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


class ModelUnavailable(Bi2Error):
    """A model couldn't answer: its provider failed or refused the request, or its answer
    wasn't of the shape asked for."""


class BudgetUsedUp(ModelUnavailable):
    """A model's budget is used up for now, like a free tier's requests for the day, or the
    model calls one site may make."""
