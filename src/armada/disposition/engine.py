"""Unified disposition engine.

One codepath for presenting a knowledge change and recording the user's
decision. The terminology adapts to context:

  Upstream (pull):  include / exclude / defer
  Peer (proposal):  accept / modify / decline

The underlying state machine is shared. A DispositionDecision maps to
the same grain state regardless of which mode produced it.
"""

import datetime
import enum
from dataclasses import dataclass, field

import armada.models.grain as grain_mod


class DispositionMode(enum.StrEnum):
    UPSTREAM = "upstream"
    PEER = "peer"


class DispositionDecision(enum.StrEnum):
    """Unified decision values that map to grain Disposition."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    DEFER = "defer"

    def to_grain_disposition(self) -> grain_mod.Disposition:
        return grain_mod.Disposition(self.value)


# Labels shown to the user per mode
DECISION_LABELS: dict[DispositionMode, dict[DispositionDecision, str]] = {
    DispositionMode.UPSTREAM: {
        DispositionDecision.INCLUDE: "Include",
        DispositionDecision.EXCLUDE: "Exclude",
        DispositionDecision.DEFER: "Defer",
    },
    DispositionMode.PEER: {
        DispositionDecision.INCLUDE: "Accept",
        DispositionDecision.EXCLUDE: "Decline",
        DispositionDecision.DEFER: "Defer",
    },
}

DECISION_DESCRIPTIONS: dict[DispositionMode, dict[DispositionDecision, str]] = {
    DispositionMode.UPSTREAM: {
        DispositionDecision.INCLUDE: "Incorporate into my instructions (adapted to my structure)",
        DispositionDecision.EXCLUDE: "Not relevant, don't resurface until major change",
        DispositionDecision.DEFER: "Relevant but not now, revisit later",
    },
    DispositionMode.PEER: {
        DispositionDecision.INCLUDE: "Accept this proposal and merge",
        DispositionDecision.EXCLUDE: "Decline this proposal",
        DispositionDecision.DEFER: "Interesting but not ready to decide",
    },
}


@dataclass(frozen=True)
class DispositionContext:
    """Everything needed to present a change for disposition."""

    mode: DispositionMode
    source_name: str
    grain_id: str
    grain_description: str
    source_content: str | None = None
    local_content: str | None = None
    diff_summary: str | None = None
    source_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DispositionPresentation:
    """A formatted presentation of a change ready for user decision."""

    context: DispositionContext
    header: str
    body: str
    options: list[tuple[DispositionDecision, str, str]]


def build_presentation(ctx: DispositionContext) -> DispositionPresentation:
    """Build a user-facing presentation from a disposition context."""
    labels = DECISION_LABELS[ctx.mode]
    descriptions = DECISION_DESCRIPTIONS[ctx.mode]

    if ctx.mode == DispositionMode.UPSTREAM:
        header = f"Upstream change from {ctx.source_name}: {ctx.grain_id}"
    else:
        header = f"Proposal from {ctx.source_name}: {ctx.grain_id}"

    body_parts = [ctx.grain_description]
    if ctx.source_paths:
        body_parts.append(f"Source: {', '.join(ctx.source_paths)}")
    if ctx.diff_summary:
        body_parts.append(f"Changes: {ctx.diff_summary}")
    body = "\n".join(body_parts)

    options = [
        (decision, labels[decision], descriptions[decision])
        for decision in DispositionDecision
    ]

    return DispositionPresentation(
        context=ctx,
        header=header,
        body=body,
        options=options,
    )


def apply_decision(
    grain_file: grain_mod.SourceGrainFile,
    grain_id: str,
    decision: DispositionDecision,
    description: str = "",
    source_paths: list[str] | None = None,
    local_paths: list[str] | None = None,
    notes: str = "",
    exclude_until: grain_mod.ExcludeUntil | None = None,
) -> grain_mod.GrainState:
    """Apply a disposition decision to grain state. Returns the updated grain."""
    existing = grain_file.get_grain(grain_id)

    grain = grain_mod.GrainState(
        semantic_id=grain_id,
        description=description or (existing.description if existing else ""),
        disposition=decision.to_grain_disposition(),
        disposition_date=datetime.date.today(),
        source_paths=source_paths or (existing.source_paths if existing else []),
        local_paths=local_paths or (existing.local_paths if existing else []),
        notes=notes or (existing.notes if existing else ""),
        exclude_until=exclude_until if decision == DispositionDecision.EXCLUDE else None,
        proposed_to=existing.proposed_to if existing else [],
    )
    grain_file.upsert_grain(grain)
    return grain
