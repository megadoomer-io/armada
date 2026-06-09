"""Configuration models for Armada network relationships and settings."""

import os
import pathlib
from typing import Self

import pydantic
import yaml


class Identity(pydantic.BaseModel):
    """The local user's identity in the Armada network."""

    name: str
    repo: str
    agent_root: pathlib.Path = pathlib.Path("~/.agents/")

    @pydantic.field_validator("agent_root", mode="before")
    @classmethod
    def expand_home(cls, v: str | pathlib.Path) -> pathlib.Path:
        return pathlib.Path(v).expanduser()


class UpstreamSource(pydantic.BaseModel):
    """A source repo to pull knowledge from (one-directional)."""

    name: str
    repo: str
    paths: list[str] = pydantic.Field(default_factory=list)


class PeerSource(pydantic.BaseModel):
    """A peer repo for bidirectional knowledge exchange."""

    name: str
    repo: str
    paths: list[str] = pydantic.Field(default_factory=list)


class DownstreamTarget(pydantic.BaseModel):
    """A convergence target that receives knowledge after peer consensus."""

    name: str
    repo: str
    paths: list[str] = pydantic.Field(default_factory=list)
    convergence_threshold: int = 2


class Settings(pydantic.BaseModel):
    """User-facing settings for sync behavior and PR throttling."""

    max_open_proposals: int = 3
    sync_check_on_session_start: bool = True
    proposal_batch_size: int = 2
    auto_fetch_interval: str = "daily"


class Preferences(pydantic.BaseModel):
    """User tool preferences for external system adapters."""

    model_config = pydantic.ConfigDict(extra="allow")

    github_client: str = "mcp"


class ArmadaConfig(pydantic.BaseModel):
    """Top-level Armada configuration (config.yaml)."""

    version: int = 1
    identity: Identity
    upstreams: list[UpstreamSource] = pydantic.Field(default_factory=list)
    peers: list[PeerSource] = pydantic.Field(default_factory=list)
    downstreams: list[DownstreamTarget] = pydantic.Field(default_factory=list)
    settings: Settings = pydantic.Field(default_factory=Settings)
    preferences: Preferences = pydantic.Field(default_factory=Preferences)

    @classmethod
    def load(cls, path: pathlib.Path | None = None) -> Self:
        """Load config from a YAML file, defaulting to XDG/env-based path."""
        if path is None:
            path = config_dir() / "config.yaml"
        raw = path.read_text()
        data = yaml.safe_load(raw)
        return cls.model_validate(data)

    def save(self, path: pathlib.Path | None = None) -> None:
        """Write config to a YAML file."""
        if path is None:
            path = config_dir() / "config.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def config_dir() -> pathlib.Path:
    """Resolve the Armada config directory (env override > XDG > default)."""
    if env := os.environ.get("ARMADA_CONFIG_DIR"):
        return pathlib.Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    return pathlib.Path(xdg).expanduser() / "armada"


def state_dir() -> pathlib.Path:
    """Resolve the Armada state directory."""
    if env := os.environ.get("ARMADA_STATE_DIR"):
        return pathlib.Path(env)
    xdg = os.environ.get("XDG_STATE_HOME", "~/.local/state")
    return pathlib.Path(xdg).expanduser() / "armada"


def cache_dir() -> pathlib.Path:
    """Resolve the Armada cache directory."""
    if env := os.environ.get("ARMADA_CACHE_DIR"):
        return pathlib.Path(env)
    xdg = os.environ.get("XDG_CACHE_HOME", "~/.cache")
    return pathlib.Path(xdg).expanduser() / "armada"
