import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Paths:
    library_dir: Path
    catalog_db: Path
    work_dir: Path


@dataclass(frozen=True)
class Rclone:
    exe: str
    library_remote: str
    catalog_remote: str
    backups_remote: str
    transfers: int
    max_delete: int


@dataclass(frozen=True)
class Vps:
    agent_host: str


@dataclass(frozen=True)
class Daily:
    hour: int
    timezone: ZoneInfo
    command: tuple[str, ...]
    models: tuple[str, ...]
    timeout_s: int
    retry_s: int

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23:
            raise ConfigError("daily.hour: must be within 0..23")


@dataclass(frozen=True)
class Schedule:
    publish_every_s: int
    backup_keep_days: int


@dataclass(frozen=True)
class Deploy:
    admin_host: str
    web_dist: Path


@dataclass(frozen=True)
class AgentConfig:
    paths: Paths
    rclone: Rclone
    vps: Vps
    daily: Daily
    schedule: Schedule
    deploy: Deploy


def default_path() -> Path:
    if explicit := os.environ.get("MUSE_AGENT_CONFIG"):
        return Path(explicit)
    appdata = os.environ.get("APPDATA")
    roaming = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return roaming / "muse" / "agent.toml"


def load(path: Path | None = None) -> AgentConfig:
    source = path or default_path()
    try:
        with source.open("rb") as handle:
            return build(AgentConfig, tomllib.load(handle), "")
    except OSError as error:
        raise ConfigError(f"{source}: cannot read: {error.strerror or error}") from error
    except (tomllib.TOMLDecodeError, ConfigError) as error:
        raise ConfigError(f"{source}: {error}") from error


def build(kind: type[Any], table: Mapping[str, object], prefix: str) -> Any:
    expected = {field.name: field.type for field in fields(kind)}
    for key in table:
        if key not in expected:
            raise ConfigError(f"{prefix}{key}: unknown key")
    values: dict[str, object] = {}
    for key, value_type in expected.items():
        where = f"{prefix}{key}"
        if key not in table:
            raise ConfigError(f"{where}: missing")
        value = table[key]
        if isinstance(value_type, type) and is_dataclass(value_type):
            if not isinstance(value, dict):
                raise ConfigError(f"{where}: must be a table")
            values[key] = build(value_type, value, f"{where}.")
        else:
            values[key] = CONVERTERS[value_type](value, where)
    return kind(**values)


def to_text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}: must be a non-empty string")
    return value


def to_path(value: object, where: str) -> Path:
    return Path(to_text(value, where))


def to_int(value: object, where: str) -> int:
    if type(value) is not int:
        raise ConfigError(f"{where}: must be an integer")
    return value


def to_texts(value: object, where: str) -> tuple[str, ...]:
    items = value if isinstance(value, list) else []
    if not items or not all(isinstance(item, str) and item for item in items):
        raise ConfigError(f"{where}: must be a non-empty list of strings")
    return tuple(items)


def to_zone(value: object, where: str) -> ZoneInfo:
    name = to_text(value, where)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as error:
        raise ConfigError(f"{where}: unknown time zone {name!r}") from error


CONVERTERS: dict[object, Callable[[object, str], object]] = {
    str: to_text,
    Path: to_path,
    int: to_int,
    tuple[str, ...]: to_texts,
    ZoneInfo: to_zone,
}
