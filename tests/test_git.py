"""Tests for git cache clone management and structural pre-filter."""

import pathlib
import subprocess
import textwrap

import pytest

import armada.git.cache as cache_mod
import armada.git.filter as filter_mod


def _run_git(cwd: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _create_fixture_repo(path: pathlib.Path) -> pathlib.Path:
    """Create a bare git repo with initial content for testing."""
    repo = path / "upstream.git"
    repo.mkdir(parents=True)
    _run_git(repo, "init", "--bare")
    return repo


def _create_working_copy(bare_repo: pathlib.Path, work_dir: pathlib.Path) -> pathlib.Path:
    """Clone the bare repo into a working directory for making commits."""
    clone = work_dir / "work"
    _run_git(work_dir, "clone", str(bare_repo), str(clone))
    _run_git(clone, "config", "user.email", "test@test.com")
    _run_git(clone, "config", "user.name", "Test")
    return clone


def _commit_file(repo: pathlib.Path, path: str, content: str, message: str) -> str:
    """Write a file, stage it, commit, push, and return the SHA."""
    full_path = repo / path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content)
    _run_git(repo, "add", path)
    _run_git(repo, "commit", "-m", message)
    _run_git(repo, "push")
    return _run_git(repo, "rev-parse", "HEAD").strip()


def _delete_file(repo: pathlib.Path, path: str, message: str) -> str:
    """Delete a file, commit, push, and return the SHA."""
    _run_git(repo, "rm", path)
    _run_git(repo, "commit", "-m", message)
    _run_git(repo, "push")
    return _run_git(repo, "rev-parse", "HEAD").strip()


def _rename_file(repo: pathlib.Path, old_path: str, new_path: str, message: str) -> str:
    """Rename a file, commit, push, and return the SHA."""
    full_new = repo / new_path
    full_new.parent.mkdir(parents=True, exist_ok=True)
    _run_git(repo, "mv", old_path, new_path)
    _run_git(repo, "commit", "-m", message)
    _run_git(repo, "push")
    return _run_git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def fixture_repo(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, str]:
    """Create a bare repo + working copy with initial content. Returns (bare, work, initial_sha)."""
    bare = _create_fixture_repo(tmp_path)
    work = _create_working_copy(bare, tmp_path)

    (work / "knowledge").mkdir(parents=True, exist_ok=True)
    (work / "knowledge" / "kubernetes.md").write_text(
        textwrap.dedent("""\
            # Kubernetes Knowledge

            Use kustomize for manifest management.
            Always use --context with kubectl.
        """)
    )
    (work / "skills").mkdir(parents=True, exist_ok=True)
    (work / "skills" / "pr-scan.md").write_text(
        textwrap.dedent("""\
            # PR Scan Skill

            Discover open PRs across repos.
        """)
    )
    _run_git(work, "add", "knowledge/kubernetes.md", "skills/pr-scan.md")
    _run_git(work, "commit", "-m", "Initial content")
    _run_git(work, "push")
    initial_sha = _run_git(work, "rev-parse", "HEAD").strip()

    return bare, work, initial_sha


class TestCacheClone:
    @pytest.mark.unit
    def test_remote_url_shorthand(self) -> None:
        clone = cache_mod.CacheClone("test", "org/repo")
        assert clone.remote_url == "https://github.com/org/repo.git"

    @pytest.mark.unit
    def test_remote_url_full(self) -> None:
        clone = cache_mod.CacheClone("test", "https://github.com/org/repo.git")
        assert clone.remote_url == "https://github.com/org/repo.git"

    @pytest.mark.unit
    def test_remote_url_ssh(self) -> None:
        clone = cache_mod.CacheClone("test", "git@github.com:org/repo.git")
        assert clone.remote_url == "git@github.com:org/repo.git"

    @pytest.mark.unit
    def test_exists_false(self, tmp_path: pathlib.Path) -> None:
        clone = cache_mod.CacheClone("test", "org/repo", cache_root=tmp_path)
        assert not clone.exists

    @pytest.mark.integration
    def test_clone_and_operations(
        self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path
    ) -> None:
        bare, _, _ = fixture_repo
        cache_root = tmp_path / "cache"
        cache_root.mkdir()

        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        assert clone.exists
        head = clone.head_rev()
        assert len(head) == 40

    @pytest.mark.integration
    def test_fetch(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, work, _ = fixture_repo
        cache_root = tmp_path / "cache"
        cache_root.mkdir()

        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()
        first_head = clone.head_rev()

        _commit_file(work, "knowledge/new.md", "# New\n", "Add new file")
        clone.fetch()
        branch = clone.default_branch()
        _run_git(clone.clone_path, "merge", f"origin/{branch}", "--ff-only")
        second_head = clone.head_rev()

        assert first_head != second_head

    @pytest.mark.integration
    def test_ensure_clones_if_missing(
        self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path
    ) -> None:
        bare, _, _ = fixture_repo
        cache_root = tmp_path / "cache"
        cache_root.mkdir()

        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        assert not clone.exists
        clone.ensure()
        assert clone.exists

    @pytest.mark.integration
    def test_diff_names(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, work, initial_sha = fixture_repo
        _commit_file(work, "knowledge/new.md", "# New\n", "Add new")

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        changed = clone.diff_names(initial_sha)
        assert "knowledge/new.md" in changed

    @pytest.mark.integration
    def test_show_file(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, _, _ = fixture_repo
        cache_root = tmp_path / "cache"
        cache_root.mkdir()

        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        content = clone.show_file("knowledge/kubernetes.md")
        assert content is not None
        assert "kustomize" in content

        missing = clone.show_file("nonexistent.md")
        assert missing is None

    @pytest.mark.integration
    def test_detect_renames(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, work, initial_sha = fixture_repo
        _rename_file(work, "skills/pr-scan.md", "skills/pr-discovery.md", "Rename pr-scan")

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        renames = clone.detect_renames(initial_sha)
        assert len(renames) >= 1
        old_paths = [r[0] for r in renames]
        new_paths = [r[1] for r in renames]
        assert "skills/pr-scan.md" in old_paths
        assert "skills/pr-discovery.md" in new_paths


class TestStructuralPreFilter:
    @pytest.mark.integration
    def test_new_file(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, work, initial_sha = fixture_repo
        _commit_file(work, "knowledge/helm.md", "# Helm\n\nUse app-template.\n", "Add helm")

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        changes = filter_mod.structural_pre_filter(clone, initial_sha)
        new_files = [c for c in changes if c.kind == filter_mod.ChangeKind.NEW_FILE]
        assert any(c.path == "knowledge/helm.md" for c in new_files)

    @pytest.mark.integration
    def test_deleted_file(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, work, initial_sha = fixture_repo
        _delete_file(work, "skills/pr-scan.md", "Remove pr-scan")

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        changes = filter_mod.structural_pre_filter(clone, initial_sha)
        deleted = [c for c in changes if c.kind == filter_mod.ChangeKind.DELETED]
        assert any(c.path == "skills/pr-scan.md" for c in deleted)

    @pytest.mark.integration
    def test_rename_only(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, work, initial_sha = fixture_repo
        _rename_file(work, "skills/pr-scan.md", "skills/pr-discovery.md", "Rename only")

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        changes = filter_mod.structural_pre_filter(clone, initial_sha)
        rename_changes = [c for c in changes if c.kind == filter_mod.ChangeKind.RENAME_ONLY]
        assert len(rename_changes) >= 1
        assert rename_changes[0].old_path == "skills/pr-scan.md"

    @pytest.mark.integration
    def test_content_delta(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, work, initial_sha = fixture_repo
        _commit_file(
            work,
            "knowledge/kubernetes.md",
            textwrap.dedent("""\
                # Kubernetes Knowledge

                Use kustomize for manifest management.
                Always use --context with kubectl.
                Use kdrift for manifest drift detection.
            """),
            "Add kdrift guidance",
        )

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        changes = filter_mod.structural_pre_filter(clone, initial_sha)
        deltas = [c for c in changes if c.kind == filter_mod.ChangeKind.CONTENT_DELTA]
        assert any(c.path == "knowledge/kubernetes.md" for c in deltas)

    @pytest.mark.integration
    def test_whitespace_only(
        self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path
    ) -> None:
        bare, work, initial_sha = fixture_repo
        _commit_file(
            work,
            "knowledge/kubernetes.md",
            textwrap.dedent("""\
                # Kubernetes Knowledge

                Use kustomize for manifest management.
                Always use --context with kubectl.

            """),
            "Add trailing whitespace",
        )

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        changes = filter_mod.structural_pre_filter(clone, initial_sha)
        ws = [c for c in changes if c.kind == filter_mod.ChangeKind.WHITESPACE_ONLY]
        assert any(c.path == "knowledge/kubernetes.md" for c in ws)

    @pytest.mark.integration
    def test_path_filtering(self, fixture_repo: tuple[pathlib.Path, pathlib.Path, str], tmp_path: pathlib.Path) -> None:
        bare, work, initial_sha = fixture_repo
        _commit_file(work, "knowledge/helm.md", "# Helm\n", "Add helm")
        _commit_file(work, "unrelated/config.md", "# Config\n", "Add config")

        cache_root = tmp_path / "cache"
        cache_root.mkdir()
        clone = cache_mod.CacheClone("upstream", str(bare), cache_root=cache_root)
        clone.clone()

        changes = filter_mod.structural_pre_filter(clone, initial_sha, paths=["knowledge/"])
        paths = [c.path for c in changes]
        assert "knowledge/helm.md" in paths
        assert "unrelated/config.md" not in paths
