"""OKF v0.2 wire-format serializers for grains.

Renders a :class:`~armada.models.grain.GrainState` (plus its content body) to a
conformant OKF v0.2 concept and parses one back. The OKF concept is armada's
shared **wire format**; the per-source local ledger (dispositions kept private,
revs, and non-accepted proposals) stays in grain state and does not travel.

Field mapping (see dotfiles ``docs/okf-adoption-eval.md``, decisions D1-D5):

- ``type: Grain`` uniformly, with the grain's nature as the ``kind:`` extension  (D2)
- ``semantic_id`` kept as an extension key = the canonical identity             (D1)
- accepted proposals -> ``verified[]``, each carrying a ``group:`` field so
  per-group convergence is reconstructable from the shared concept              (D3=a)
- ``source_paths`` -> ``sources[].resource``                                    (provenance)
- ``disposition`` / ``audiences`` / ``exclude_until`` / ``local_paths`` /
  ``notes`` -> extension keys, emitted only when ``include_local``              (D4)
- accepting members are ``human:<member>`` actors                               (D5)

Timestamp rules (from cross-validating with scaccogatto/okf-skills ``--strict``):
``generated.at`` / ``verified.at`` are RFC3339 datetimes; date-only fields would
be ``YYYY-MM-DD``. All are emitted as quoted strings so YAML does not auto-parse
them into datetime objects.
"""

import dataclasses
import datetime
from typing import Any

import yaml

import armada.models.grain as grain_mod

OKF_TYPE = "Grain"
_HUMAN = "human:"


def _rfc3339(d: datetime.date) -> str:
    """Render a date as an RFC3339 datetime string (midnight UTC)."""
    return f"{d.isoformat()}T00:00:00Z"


@dataclasses.dataclass
class ParsedGrain:
    """The result of parsing an OKF concept back into armada terms."""

    grain: grain_mod.GrainState
    body: str = ""
    generated_by: str | None = None
    generated_at: datetime.date | None = None


def to_okf(
    grain: grain_mod.GrainState,
    *,
    generated_by: str,
    generated_at: datetime.date,
    body: str = "",
    include_local: bool = True,
) -> str:
    """Render ``grain`` as a conformant OKF v0.2 concept string.

    ``generated_by`` is the originating actor (e.g. ``human:mikedougherty``);
    ``generated_at`` its date. ``body`` is the grain's knowledge content (the
    OKF concept body). ``include_local`` controls whether recipient-local fields
    (disposition/audiences/exclude_until/local_paths/notes) are emitted.
    """
    fm: dict[str, Any] = {"type": OKF_TYPE}
    if grain.kind:
        fm["kind"] = grain.kind
    if grain.description:
        fm["description"] = grain.description
    fm["semantic_id"] = grain.semantic_id
    fm["generated"] = {"by": generated_by, "at": _rfc3339(generated_at)}

    verified: list[dict[str, Any]] = []
    for proposal in grain.proposed_to:
        if proposal.status is not grain_mod.ProposalStatus.ACCEPTED:
            continue  # D4: only accepted proposals travel as trust
        entry: dict[str, Any] = {"by": f"{_HUMAN}{proposal.target}"}
        if proposal.accepted_at is not None:
            entry["at"] = _rfc3339(proposal.accepted_at)
        if proposal.group is not None:
            entry["group"] = proposal.group  # D3=a
        verified.append(entry)
    if verified:
        fm["verified"] = verified

    if grain.source_paths:
        fm["sources"] = [{"resource": path} for path in grain.source_paths]

    if include_local:
        if grain.disposition is not None:
            fm["disposition"] = grain.disposition.value
        if grain.disposition_date is not None:
            fm["disposition_date"] = grain.disposition_date.isoformat()
        if grain.audiences:
            fm["audiences"] = list(grain.audiences)
        if grain.exclude_until is not None:
            fm["exclude_until"] = grain.exclude_until.value
        if grain.local_paths:
            fm["local_paths"] = list(grain.local_paths)
        if grain.notes:
            fm["notes"] = grain.notes

    fm_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
    if body:
        return f"---\n{fm_yaml}---\n\n{body.strip()}\n"
    return f"---\n{fm_yaml}---\n"


def from_okf(text: str) -> ParsedGrain:
    """Parse an OKF concept string back into a :class:`ParsedGrain`.

    Only accepted-proposal trust survives the round trip (``verified[]`` ->
    accepted proposals); pending/open/declined proposals and PR numbers are
    local-only and never travel.
    """
    if not text.startswith("---"):
        raise ValueError("not an OKF concept: missing leading frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise ValueError("not an OKF concept: unterminated frontmatter block")
    fm = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4 :].lstrip("\n").rstrip() + "\n" if text[end + 4 :].strip() else ""

    proposed: list[grain_mod.GrainProposal] = []
    for entry in fm.get("verified") or []:
        by = str(entry.get("by", ""))
        target = by[len(_HUMAN) :] if by.startswith(_HUMAN) else by
        at = entry.get("at")
        proposed.append(
            grain_mod.GrainProposal(
                target=target,
                group=entry.get("group"),
                status=grain_mod.ProposalStatus.ACCEPTED,
                accepted_at=datetime.date.fromisoformat(str(at)[:10]) if at else None,
            )
        )

    source_paths = [s["resource"] for s in (fm.get("sources") or []) if isinstance(s, dict) and "resource" in s]
    disposition = fm.get("disposition")
    disposition_date = fm.get("disposition_date")
    exclude_until = fm.get("exclude_until")

    grain = grain_mod.GrainState(
        semantic_id=fm.get("semantic_id") or "",
        description=fm.get("description", ""),
        kind=fm.get("kind"),
        disposition=grain_mod.Disposition(disposition) if disposition else None,
        disposition_date=datetime.date.fromisoformat(str(disposition_date)) if disposition_date else None,
        audiences=list(fm.get("audiences") or []),
        source_paths=source_paths,
        local_paths=list(fm.get("local_paths") or []),
        notes=fm.get("notes", ""),
        exclude_until=grain_mod.ExcludeUntil(exclude_until) if exclude_until else None,
        proposed_to=proposed,
    )

    generated = fm.get("generated") or {}
    generated_at = generated.get("at")
    return ParsedGrain(
        grain=grain,
        body=body,
        generated_by=generated.get("by"),
        generated_at=datetime.date.fromisoformat(str(generated_at)[:10]) if generated_at else None,
    )
