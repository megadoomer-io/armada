"""Models for proposal queues — per-target pending and active proposals."""

import datetime
import enum
import pathlib
from typing import Self

import pydantic
import yaml

import armada.models.config as config


class ProposalPriority(int, enum.Enum):
    HIGH = 1
    MEDIUM = 2
    LOW = 3


class EstimatedValue(enum.StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActiveProposal(pydantic.BaseModel):
    """A proposal that has been opened as a PR."""

    grain_id: str
    pr_number: int
    pr_url: str
    opened: datetime.date
    status: str = "open"


class PendingProposal(pydantic.BaseModel):
    """A proposal queued but not yet opened as a PR."""

    grain_id: str
    priority: ProposalPriority = ProposalPriority.MEDIUM
    description: str = ""
    estimated_value: EstimatedValue = EstimatedValue.MEDIUM


class ProposalQueue(pydantic.BaseModel):
    """Per-target proposal queue (queues/<target>.yaml)."""

    target: str
    max_open: int = 3
    active_proposals: list[ActiveProposal] = pydantic.Field(default_factory=list)
    pending_proposals: list[PendingProposal] = pydantic.Field(default_factory=list)

    @property
    def open_count(self) -> int:
        return sum(1 for p in self.active_proposals if p.status == "open")

    @property
    def at_capacity(self) -> bool:
        return self.open_count >= self.max_open

    def get_next_pending(self) -> PendingProposal | None:
        """Return the highest priority pending proposal, or None."""
        if not self.pending_proposals:
            return None
        return min(self.pending_proposals, key=lambda p: p.priority.value)

    def activate(self, grain_id: str, pr_number: int, pr_url: str) -> None:
        """Move a pending proposal to active."""
        self.pending_proposals = [p for p in self.pending_proposals if p.grain_id != grain_id]
        self.active_proposals.append(
            ActiveProposal(
                grain_id=grain_id,
                pr_number=pr_number,
                pr_url=pr_url,
                opened=datetime.date.today(),
            )
        )

    @classmethod
    def load(cls, target_name: str, state_path: pathlib.Path | None = None) -> Self:
        """Load queue for a target. Returns empty queue if file doesn't exist."""
        if state_path is None:
            state_path = config.state_dir() / "queues" / f"{target_name}.yaml"
        if not state_path.exists():
            return cls(target=target_name)
        raw = state_path.read_text()
        data = yaml.safe_load(raw) or {}
        return cls.model_validate(data)

    def save(self, state_path: pathlib.Path | None = None) -> None:
        if state_path is None:
            state_path = config.state_dir() / "queues" / f"{self.target}.yaml"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        state_path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
