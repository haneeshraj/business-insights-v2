"""One resolver per output field. Each is a list of steps run by the shared cascade in
cascade.py, and the registry of resolvers lives in this file.

Belongs here: the logic that decides a field's value from Evidence, using the ports in the
RunContext.

Doesn't belong here: provider-specific code. Resolvers reach models, search and geocoding only
through the ports.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Final

from bi2.core.context import RunContext
from bi2.core.models import Evidence, FieldResult
from bi2.resolvers.email import resolve_email
from bi2.resolvers.logo import resolve_logo
from bi2.resolvers.name import resolve_name
from bi2.resolvers.phone import resolve_phone
from bi2.resolvers.social import resolve_social_links

type Resolver = Callable[[Evidence, RunContext], Awaitable[FieldResult[Any]]]

# The resolver for each output field built so far. A field missing here is reported as not
# built yet, never guessed. Adding a field means adding its resolver here.
RESOLVERS: Final[dict[str, Resolver]] = {
    "company_name": resolve_name,
    "logo": resolve_logo,
    "phone": resolve_phone,
    "email": resolve_email,
    "social_links": resolve_social_links,
}
