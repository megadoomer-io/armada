"""Chunked comparison — group file changes into LLM-sized chunks.

For incremental syncs, instead of sending the entire instruction set to the
LLM, we group related file changes and send them as individual comparison
requests. This reduces token cost from O(full repo) to O(changed files).
"""

from dataclasses import dataclass, field

import armada.git.filter as filter_mod


@dataclass(frozen=True)
class ComparisonChunk:
    """A group of related file changes to compare in one LLM call."""

    source_name: str
    changes: list[filter_mod.FileChange]
    source_contents: dict[str, str]
    local_contents: dict[str, str | None] = field(default_factory=dict)

    @property
    def paths(self) -> list[str]:
        return [c.path for c in self.changes]

    @property
    def is_new_file_only(self) -> bool:
        return all(c.kind == filter_mod.ChangeKind.NEW_FILE for c in self.changes)

    @property
    def token_estimate(self) -> int:
        """Rough token estimate (4 chars per token)."""
        total_chars = sum(len(v) for v in self.source_contents.values())
        total_chars += sum(len(v) for v in self.local_contents.values() if v)
        return total_chars // 4


def chunk_changes(
    changes: list[filter_mod.FileChange],
    source_name: str,
    source_contents: dict[str, str],
    local_contents: dict[str, str | None] | None = None,
    max_tokens_per_chunk: int = 8000,
) -> list[ComparisonChunk]:
    """Group file changes into chunks for LLM comparison.

    Groups by directory prefix first (related files often share context),
    then splits groups that exceed the token budget.
    """
    if not changes:
        return []

    local = local_contents or {}

    meaningful = [
        c for c in changes
        if c.kind in (filter_mod.ChangeKind.CONTENT_DELTA, filter_mod.ChangeKind.NEW_FILE)
    ]

    if not meaningful:
        return []

    groups: dict[str, list[filter_mod.FileChange]] = {}
    for change in meaningful:
        prefix = _directory_prefix(change.path)
        groups.setdefault(prefix, []).append(change)

    chunks: list[ComparisonChunk] = []
    for group_changes in groups.values():
        group_source = {c.path: source_contents[c.path] for c in group_changes if c.path in source_contents}
        group_local = {c.path: local.get(c.path) for c in group_changes}

        chunk = ComparisonChunk(
            source_name=source_name,
            changes=group_changes,
            source_contents=group_source,
            local_contents=group_local,
        )

        if chunk.token_estimate <= max_tokens_per_chunk:
            chunks.append(chunk)
        else:
            for change in group_changes:
                single_source = {change.path: source_contents[change.path]} if change.path in source_contents else {}
                single_local = {change.path: local.get(change.path)}
                chunks.append(ComparisonChunk(
                    source_name=source_name,
                    changes=[change],
                    source_contents=single_source,
                    local_contents=single_local,
                ))

    return chunks


def _directory_prefix(path: str) -> str:
    """Extract the top-level directory from a path."""
    parts = path.split("/")
    return parts[0] if len(parts) > 1 else ""
