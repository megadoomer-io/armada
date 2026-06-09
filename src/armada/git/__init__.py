"""Git operations for Armada — cache clone management and structural pre-filter."""

from armada.git.cache import CacheClone
from armada.git.filter import ChangeKind, FileChange, structural_pre_filter

__all__ = [
    "CacheClone",
    "ChangeKind",
    "FileChange",
    "structural_pre_filter",
]
