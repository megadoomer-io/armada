"""Structural pre-filter for change detection.

Classifies file changes between two revisions before sending anything
to the LLM. The goal is to skip trivial changes (renames, whitespace,
formatting) and surface only meaningful content deltas for semantic analysis.
"""

import enum
import re
from dataclasses import dataclass

import armada.git.cache as cache_mod


class ChangeKind(enum.StrEnum):
    """Classification of a file change."""

    RENAME_ONLY = "rename_only"
    WHITESPACE_ONLY = "whitespace_only"
    NEW_FILE = "new_file"
    DELETED = "deleted"
    CONTENT_DELTA = "content_delta"


@dataclass(frozen=True)
class FileChange:
    """A classified file change between two revisions."""

    path: str
    kind: ChangeKind
    old_path: str | None = None


_WHITESPACE_RE = re.compile(r"^[-+][\s]*$")


def _is_whitespace_only_diff(diff_text: str) -> bool:
    """Check if a diff contains only whitespace changes."""
    for line in diff_text.splitlines():
        if not line.startswith(("+", "-")):
            continue
        if line.startswith(("+++", "---")):
            continue
        if not _WHITESPACE_RE.match(line):
            return False
    return True


def structural_pre_filter(
    clone: cache_mod.CacheClone,
    from_rev: str,
    to_rev: str = "HEAD",
    paths: list[str] | None = None,
) -> list[FileChange]:
    """Classify all file changes between two revisions.

    Returns a list of FileChange objects, each tagged with a ChangeKind.
    The caller decides which kinds warrant LLM analysis (typically only
    CONTENT_DELTA and NEW_FILE).
    """
    renames = clone.detect_renames(from_rev, to_rev)
    rename_old_paths = {old for old, _ in renames}
    rename_new_paths = {new for _, new in renames}

    changed_files = clone.diff_names(from_rev, to_rev)

    if paths:
        changed_files = [f for f in changed_files if any(f.startswith(p) for p in paths)]

    changes: list[FileChange] = []

    for old_path, new_path in renames:
        if paths and not any(new_path.startswith(p) for p in paths):
            continue
        old_content = clone.show_file(old_path, from_rev)
        new_content = clone.show_file(new_path, to_rev)
        if old_content == new_content:
            changes.append(FileChange(path=new_path, kind=ChangeKind.RENAME_ONLY, old_path=old_path))
        else:
            changes.append(FileChange(path=new_path, kind=ChangeKind.CONTENT_DELTA, old_path=old_path))

    for file_path in changed_files:
        if file_path in rename_old_paths or file_path in rename_new_paths:
            continue

        old_content = clone.show_file(file_path, from_rev)
        new_content = clone.show_file(file_path, to_rev)

        if old_content is None and new_content is not None:
            changes.append(FileChange(path=file_path, kind=ChangeKind.NEW_FILE))
        elif old_content is not None and new_content is None:
            changes.append(FileChange(path=file_path, kind=ChangeKind.DELETED))
        elif old_content is not None and new_content is not None:
            diff = clone.diff_content(from_rev, to_rev, paths=[file_path])
            if _is_whitespace_only_diff(diff):
                changes.append(FileChange(path=file_path, kind=ChangeKind.WHITESPACE_ONLY))
            else:
                changes.append(FileChange(path=file_path, kind=ChangeKind.CONTENT_DELTA))

    return changes
