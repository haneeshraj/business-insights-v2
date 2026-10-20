"""Business Insights v2: find a business's name, logo, phone, email, social links, merchant
category code (MCC) and headquarters address from its website.

docs/codebase.md describes how the package is organized. Keep this file light: every
import of a subpackage runs it first.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("business-insights")
except PackageNotFoundError:  # a source tree that hasn't been installed
    __version__ = "0.0.0+unknown"

# How v2 introduces itself to services that ask every client to say who it is and how to reach
# its maker, like Wikimedia's.
USER_AGENT = f"bi2/{__version__} (https://github.com/haneeshraj/business-insights-v2)"
