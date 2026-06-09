"""Models for grain state tracking — per-source disposition records."""

import datetime
import enum
import pathlib
from typing import Self

import pydantic
import yaml

import armada.models.config as config


class Disposition(enum.StrEnum):
    """How the user has dispositioned a grain from an upstream or peer."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    DEFER = "defer"


class ExcludeUntil(enum.StrEnum):
    """When an excluded grain should be resurfaced."""

    MAJOR_CHANGE = "major_change"
    NEVER = "never"


class ProposalStatus(enum.StrEnum):
    """Status of a grain proposal to a peer or downstream."""

    PENDING = "pending"
    OPEN = "open"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class GrainProposal(pydantic.BaseModel):
    """Tracks a proposal of this grain to another target."""

    target: str
    pr_number: int | None = None
    pr_url: str | None = None
    status: ProposalStatus = ProposalStatus.PENDING


class GrainState(pydantic.BaseModel):
    """State of a single knowledge grain from a source repo.

    The semantic_id is LLM-assigned and stable across file renames.
    File paths are metadata, not identity.
    """

    semantic_id: str
    description: str = ""
    disposition: Disposition | None = None
    disposition_date: datetime.date | None = None
    source_paths: list[str] = pydantic.Field(default_factory=list)
    local_paths: list[str] = pydantic.Field(default_factory=list)
    notes: str = ""
    exclude_until: ExcludeUntil | None = None
    proposed_to: list[GrainProposal] = pydantic.Field(default_factory=list)


class SourceGrainFile(pydantic.BaseModel):
    """Per-source grain tracking file (grains/<source>.yaml)."""

    source: str
    last_reviewed_rev: str | None = None
    current_rev: str | None = None
    grains: list[GrainState] = pydantic.Field(default_factory=list)

    def get_grain(self, semantic_id: str) -> GrainState | None:
        for grain in self.grains:
            if grain.semantic_id == semantic_id:
                return grain
        return None

    def upsert_grain(self, grain: GrainState) -> None:
        """Insert or update a grain by semantic_id."""
        for i, existing in enumerate(self.grains):
            if existing.semantic_id == grain.semantic_id:
                self.grains[i] = grain
                return
        self.grains.append(grain)

    @classmethod
    def load(cls, source_name: str, state_path: pathlib.Path | None = None) -> Self:
        """Load grain state for a source. Returns empty state if file doesn't exist."""
        if state_path is None:
            state_path = config.state_dir() / "grains" / f"{source_name}.yaml"
        if not state_path.exists():
            return cls(source=source_name)
        raw = state_path.read_text()
        data = yaml.safe_load(raw) or {}
        return cls.model_validate(data)

    def save(self, state_path: pathlib.Path | None = None) -> None:
        if state_path is None:
            state_path = config.state_dir() / "grains" / f"{self.source}.yaml"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        state_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
