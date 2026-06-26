"""Cache clone management — shallow clones of upstream/peer repos.

All external repos are cloned into $XDG_CACHE_HOME/armada/repos/<slug>/
and never operate on the user's working git clones (prevents index lock
contention).
"""

import logging
import pathlib
import subprocess

import armada.models.config as config

logger = logging.getLogger(__name__)


class CacheCloneError(Exception):
    """Raised when a git operation on a cache clone fails."""


class CacheClone:
    """Manages a shallow clone of a remote repo in the cache directory."""

    def __init__(self, source_name: str, repo: str, cache_root: pathlib.Path | None = None) -> None:
        self.source_name = source_name
        self.repo = repo
        self._cache_root = cache_root or config.cache_dir() / "repos"
        self.clone_path = self._cache_root / source_name

    @property
    def exists(self) -> bool:
        return (self.clone_path / ".git").is_dir()

    @property
    def remote_url(self) -> str:
        """Resolve repo shorthand to a full git URL."""
        if self.repo.startswith(("https://", "git@", "ssh://", "/")):
            return self.repo
        if pathlib.Path(self.repo).exists():
            return self.repo
        return f"https://github.com/{self.repo}.git"

    def ensure(self) -> None:
        """Clone if not present, fetch if already cloned."""
        if self.exists:
            self.fetch()
        else:
            self.clone()

    def clone(self) -> None:
        """Clone the repo into the cache directory."""
        self.clone_path.mkdir(parents=True, exist_ok=True)
        self._run(
            ["git", "clone", self.remote_url, str(self.clone_path)],
            cwd=None,
        )
        logger.info("Cloned %s into %s", self.repo, self.clone_path)

    def fetch(self) -> None:
        """Fetch latest from origin."""
        self._run(["git", "fetch", "origin"], cwd=self.clone_path)
        logger.info("Fetched latest for %s", self.source_name)

    def head_rev(self) -> str:
        """Return the current HEAD SHA."""
        result = self._run(["git", "rev-parse", "HEAD"], cwd=self.clone_path, capture=True)
        return result.strip()

    def default_branch(self) -> str:
        """Return the default branch name (usually main or master)."""
        result = self._run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=self.clone_path,
            capture=True,
        )
        return result.strip().split("/")[-1]

    def diff_names(self, from_rev: str, to_rev: str = "HEAD") -> list[str]:
        """List files changed between two revisions."""
        result = self._run(
            ["git", "diff", "--name-only", from_rev, to_rev],
            cwd=self.clone_path,
            capture=True,
        )
        return [line for line in result.strip().splitlines() if line]

    def diff_stat(self, from_rev: str, to_rev: str = "HEAD") -> str:
        """Return diff --stat output between two revisions."""
        return self._run(
            ["git", "diff", "--stat", from_rev, to_rev],
            cwd=self.clone_path,
            capture=True,
        )

    def diff_content(self, from_rev: str, to_rev: str = "HEAD", paths: list[str] | None = None) -> str:
        """Return unified diff between two revisions, optionally filtered to paths."""
        cmd = ["git", "diff", from_rev, to_rev]
        if paths:
            cmd.append("--")
            cmd.extend(paths)
        return self._run(cmd, cwd=self.clone_path, capture=True)

    def show_file(self, path: str, rev: str = "HEAD") -> str | None:
        """Read a file at a specific revision. Returns None if file doesn't exist."""
        try:
            return self._run(
                ["git", "show", f"{rev}:{path}"],
                cwd=self.clone_path,
                capture=True,
            )
        except CacheCloneError:
            return None

    def detect_renames(self, from_rev: str, to_rev: str = "HEAD") -> list[tuple[str, str]]:
        """Detect file renames between two revisions. Returns (old_path, new_path) pairs."""
        result = self._run(
            ["git", "diff", "--diff-filter=R", "--name-status", "-M", from_rev, to_rev],
            cwd=self.clone_path,
            capture=True,
        )
        renames = []
        for line in result.strip().splitlines():
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 3 and parts[0].startswith("R"):
                renames.append((parts[1], parts[2]))
        return renames

    def _run(
        self,
        cmd: list[str],
        cwd: pathlib.Path | None,
        capture: bool = False,
    ) -> str:
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
                timeout=120,
            )
            return result.stdout if capture else ""
        except subprocess.CalledProcessError as e:
            raise CacheCloneError(f"Git command failed: {' '.join(cmd)}\nstderr: {e.stderr}") from e
        except subprocess.TimeoutExpired as e:
            raise CacheCloneError(f"Git command timed out after 120s: {' '.join(cmd)}") from e
