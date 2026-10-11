"""Business Insights v2: find a business's name, logo, merchant category code (MCC) and
headquarters address from its website.

docs/codebase.md describes how the package is organized. Keep this file light: every
import of a subpackage runs it first.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("business-insights")
except PackageNotFoundError:  # a source tree that hasn't been installed
    __version__ = "0.0.0+unknown"
