import os
from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

DEFAULT_CONFIG = Path("/etc/muse/muse.toml")


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsSettings(Section):
    data_dir: Path
    library_dir: Path
    catalog_db: Path
    web_dir: Path

    @property
    def users_file(self) -> Path:
        return self.data_dir / "users.json"

    @property
    def user_db(self) -> Path:
        return self.data_dir / "muse.sqlite"

    @property
    def upgrade_snapshot(self) -> Path:
        return self.data_dir / "muse.pre-upgrade.sqlite"

    @property
    def notes_dir(self) -> Path:
        return self.data_dir / "notes"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def artists_dir(self) -> Path:
        return self.data_dir / "artists"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def vapid_file(self) -> Path:
        return self.data_dir / "vapid.pem"

    @property
    def player_log(self) -> Path:
        return self.data_dir / "player.log"

    @property
    def playlists_dir(self) -> Path:
        return self.library_dir / "_Playlists"


class HttpSettings(Section):
    host: str = "127.0.0.1"
    port: int = 4535
    public_host: str
    origins: tuple[str, ...]


class PushSettings(Section):
    enabled: bool = True
    subject: str = ""

    @model_validator(mode="after")
    def subject_when_enabled(self) -> Self:
        if self.enabled and not self.subject:
            raise ValueError("push.subject is required while push is enabled")
        return self


class CacheSettings(Section):
    redis_url: str = ""


class ClockSettings(Section):
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown timezone {value!r}") from error
        return value


def config_file() -> Path:
    return Path(os.environ.get("MUSE_CONFIG", DEFAULT_CONFIG))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MUSE_", env_nested_delimiter="__", extra="forbid", frozen=True
    )

    paths: PathsSettings
    http: HttpSettings
    push: PushSettings = Field(default_factory=PushSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    clock: ClockSettings = Field(default_factory=ClockSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml = TomlConfigSettingsSource(settings_cls, toml_file=config_file())
        return init_settings, env_settings, toml


def load_settings() -> Settings:
    return Settings()
