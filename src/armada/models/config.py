"""Configuration models for Armada network relationships and settings.

Version 2 collapses the flat ``upstreams`` / ``peers`` / ``downstreams`` lists
into three clear nouns:

- ``members`` — one canonical record per person (repo, paths, ``pull`` flag).
  A member is a *peer* (proposed to) iff they belong to >=1 group; an *upstream*
  (pulled from) iff ``pull`` is True.
- ``groups`` — policy lenses. A group gates which grains are eligible for its
  members and pools their accepts for convergence. It is NOT a state partition;
  one person in two groups still has a single per-member queue.
- ``downstreams`` — sink repos that receive a grain once a group's convergence
  threshold is reached.

Audiences on a grain name the groups it may flow to. ``resolve_groups`` maps an
audience list to concrete group names; today it is the identity map, but keeping
it a function preserves the exit to a decoupled audience taxonomy with no grain
state migration.
"""

import os
import pathlib
from typing import Self

import pydantic
import yaml

ALL_GROUPS = "*"
"""Audience sentinel meaning 'every group'. Distinct from an empty list, which
means private (shared with no one). Absence never means broadcast."""


class Identity(pydantic.BaseModel):
    """The local user's identity in the Armada network."""

    name: str
    repo: str
    agent_root: pathlib.Path = pathlib.Path("~/.agents/")

    @pydantic.field_validator("agent_root", mode="before")
    @classmethod
    def expand_home(cls, v: str | pathlib.Path) -> pathlib.Path:
        return pathlib.Path(v).expanduser()


class Member(pydantic.BaseModel):
    """A person in the network, referenced by name (the dict key) from groups.

    A member is a peer (proposed to) iff they belong to >=1 group, and an
    upstream (pulled from) iff ``pull`` is True. The two roles are independent
    (a friend may become upstream-capable without joining a convergence group).
    """

    repo: str
    paths: list[str] = pydantic.Field(default_factory=list)
    pull: bool = False


class Convergence(pydantic.BaseModel):
    """A group's convergence policy: consensus pushes a grain to a downstream."""

    threshold: int = 2
    downstream: str


class Group(pydantic.BaseModel):
    """A policy lens over members. Keyed by name (the dict key) in the config.

    Carries the members eligible for grains tagged with this group's name, and
    an optional convergence block. A group without ``convergence`` never pushes
    to a downstream (pure pairwise sharing).
    """

    members: list[str] = pydantic.Field(default_factory=list)
    convergence: Convergence | None = None


class Downstream(pydantic.BaseModel):
    """A sink repo that receives knowledge after a group reaches consensus."""

    repo: str
    paths: list[str] = pydantic.Field(default_factory=list)


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
    """Top-level Armada configuration (config.yaml), schema version 2."""

    version: int = 2
    identity: Identity
    members: dict[str, Member] = pydantic.Field(default_factory=dict)
    groups: dict[str, Group] = pydantic.Field(default_factory=dict)
    downstreams: dict[str, Downstream] = pydantic.Field(default_factory=dict)
    settings: Settings = pydantic.Field(default_factory=Settings)
    preferences: Preferences = pydantic.Field(default_factory=Preferences)

    @pydantic.model_validator(mode="after")
    def check_references(self) -> Self:
        """Fail loud at load on a structurally invalid network.

        Enforces three invariants:
          (a) every ``group.members[*]`` resolves to a defined member;
          (b) every ``group.convergence.downstream`` resolves to a defined
              downstream;
          (c) no single member belongs to two convergence-bearing groups, which
              keeps the scalar ``GrainProposal.group`` sound by construction
              (at most one convergence-bearing group applies per member/grain).

        Also rejects a stale version-1 config rather than silently dropping its
        now-unknown ``upstreams`` / ``peers`` fields into an empty network.
        """
        if self.version != 2:
            raise ValueError(
                f"unsupported config version {self.version}; expected 2 "
                "(migrate the flat upstreams/peers/downstreams lists to "
                "members/groups/downstreams)"
            )

        convergence_groups_per_member: dict[str, list[str]] = {}
        for group_name, group in self.groups.items():
            for member_name in group.members:
                if member_name not in self.members:
                    raise ValueError(f"group {group_name!r} references undefined member {member_name!r}")
            if group.convergence is not None:
                if group.convergence.downstream not in self.downstreams:
                    raise ValueError(
                        f"group {group_name!r} converges to undefined downstream {group.convergence.downstream!r}"
                    )
                for member_name in group.members:
                    convergence_groups_per_member.setdefault(member_name, []).append(group_name)

        for member_name, member_groups in convergence_groups_per_member.items():
            if len(member_groups) > 1:
                raise ValueError(
                    f"member {member_name!r} belongs to multiple convergence-bearing "
                    f"groups {sorted(member_groups)!r}; a member may converge in at most one"
                )

        return self

    @property
    def pull_members(self) -> dict[str, Member]:
        """Members flagged ``pull: true`` — the sources sync pulls from."""
        return {name: member for name, member in self.members.items() if member.pull}

    def proposal_group_for(self, member: str, audiences: list[str]) -> str | None:
        """Return the group a proposal to ``member`` should be tagged with.

        The single home for the normative selection rule that prevents the
        convergence data leak: when ``member`` is eligible for a grain via two
        groups and one is convergence-bearing, the convergence-bearing group
        wins so the accept counts toward convergence. Returns None when the
        member is not eligible for any group the grain's audiences resolve to.
        """
        eligible = {
            group_name for group_name in resolve_groups(audiences, self) if member in self.groups[group_name].members
        }
        if not eligible:
            return None
        convergence_bearing = sorted(
            group_name for group_name in eligible if self.groups[group_name].convergence is not None
        )
        if convergence_bearing:
            # Invariant (c) guarantees at most one convergence-bearing group per
            # member, so this is deterministic.
            return convergence_bearing[0]
        return sorted(eligible)[0]

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


def resolve_groups(audiences: list[str], cfg: ArmadaConfig) -> set[str]:
    """Map a grain's audience list to the set of concrete group names.

    Today this is the identity map (an audience string IS a group name),
    intersected with the defined groups so an audience naming an unknown group
    is silently dropped. The ``"*"`` sentinel expands to every group; an empty
    list resolves to nothing (private). Keeping this a function preserves the
    exit to a decoupled audience taxonomy with no grain state migration.
    """
    if ALL_GROUPS in audiences:
        return set(cfg.groups)
    return set(audiences) & set(cfg.groups)


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
