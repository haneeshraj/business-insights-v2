"""The settings schema, and loading it. This is the only module that reads environment
variables.

Every setting has a default here. An environment variable overrides it: BI2_ followed by the
setting's path, with "__" between levels, like BI2_THRESHOLDS__ACCEPT=0.9. Config files and
profiles come later (see docs/codebase.md, "Configuration").
"""

from pydantic import BaseModel, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

from bi2.core.models import Confidence


class Thresholds(BaseModel):
    """How sure an answer has to be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accept: Confidence = 0.85  # needed to accept an answer; a field below it needs review


class Settings(BaseSettings):
    """Every setting a run uses."""

    model_config = SettingsConfigDict(
        env_prefix="BI2_", env_nested_delimiter="__", frozen=True, extra="forbid"
    )

    thresholds: Thresholds = Thresholds()
