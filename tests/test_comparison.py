"""Tests for comparison chunking and prompt generation."""

import pytest

import armada.comparison.chunked as chunked_mod
import armada.comparison.prompts as prompts_mod
import armada.git.filter as filter_mod


class TestChunkChanges:
    @pytest.mark.unit
    def test_empty_changes(self) -> None:
        chunks = chunked_mod.chunk_changes([], "james", {})
        assert chunks == []

    @pytest.mark.unit
    def test_filters_non_meaningful_changes(self) -> None:
        changes = [
            filter_mod.FileChange(path="a.md", kind=filter_mod.ChangeKind.RENAME_ONLY, old_path="b.md"),
            filter_mod.FileChange(path="c.md", kind=filter_mod.ChangeKind.WHITESPACE_ONLY),
            filter_mod.FileChange(path="d.md", kind=filter_mod.ChangeKind.DELETED),
        ]
        chunks = chunked_mod.chunk_changes(changes, "james", {})
        assert chunks == []

    @pytest.mark.unit
    def test_groups_by_directory(self) -> None:
        changes = [
            filter_mod.FileChange(path="rules/a.md", kind=filter_mod.ChangeKind.NEW_FILE),
            filter_mod.FileChange(path="rules/b.md", kind=filter_mod.ChangeKind.NEW_FILE),
            filter_mod.FileChange(path="skills/c.md", kind=filter_mod.ChangeKind.CONTENT_DELTA),
        ]
        contents = {"rules/a.md": "# A", "rules/b.md": "# B", "skills/c.md": "# C"}
        chunks = chunked_mod.chunk_changes(changes, "james", contents)

        assert len(chunks) == 2
        chunk_paths = [set(c.paths) for c in chunks]
        assert {"rules/a.md", "rules/b.md"} in chunk_paths
        assert {"skills/c.md"} in chunk_paths

    @pytest.mark.unit
    def test_splits_oversized_groups(self) -> None:
        large_content = "x" * 40000
        changes = [
            filter_mod.FileChange(path="rules/a.md", kind=filter_mod.ChangeKind.NEW_FILE),
            filter_mod.FileChange(path="rules/b.md", kind=filter_mod.ChangeKind.NEW_FILE),
        ]
        contents = {"rules/a.md": large_content, "rules/b.md": large_content}
        chunks = chunked_mod.chunk_changes(changes, "james", contents, max_tokens_per_chunk=8000)

        assert len(chunks) == 2
        assert chunks[0].paths == ["rules/a.md"]
        assert chunks[1].paths == ["rules/b.md"]

    @pytest.mark.unit
    def test_token_estimate(self) -> None:
        chunk = chunked_mod.ComparisonChunk(
            source_name="james",
            changes=[filter_mod.FileChange(path="a.md", kind=filter_mod.ChangeKind.NEW_FILE)],
            source_contents={"a.md": "x" * 400},
        )
        assert chunk.token_estimate == 100

    @pytest.mark.unit
    def test_is_new_file_only(self) -> None:
        new_only = chunked_mod.ComparisonChunk(
            source_name="james",
            changes=[
                filter_mod.FileChange(path="a.md", kind=filter_mod.ChangeKind.NEW_FILE),
                filter_mod.FileChange(path="b.md", kind=filter_mod.ChangeKind.NEW_FILE),
            ],
            source_contents={"a.md": "", "b.md": ""},
        )
        assert new_only.is_new_file_only

        mixed = chunked_mod.ComparisonChunk(
            source_name="james",
            changes=[
                filter_mod.FileChange(path="a.md", kind=filter_mod.ChangeKind.NEW_FILE),
                filter_mod.FileChange(path="b.md", kind=filter_mod.ChangeKind.CONTENT_DELTA),
            ],
            source_contents={"a.md": "", "b.md": ""},
        )
        assert not mixed.is_new_file_only

    @pytest.mark.unit
    def test_local_contents_included(self) -> None:
        changes = [
            filter_mod.FileChange(path="rules/k8s.md", kind=filter_mod.ChangeKind.CONTENT_DELTA),
        ]
        chunks = chunked_mod.chunk_changes(
            changes,
            "james",
            source_contents={"rules/k8s.md": "# K8s rules"},
            local_contents={"rules/k8s.md": "# My K8s rules"},
        )
        assert len(chunks) == 1
        assert chunks[0].local_contents["rules/k8s.md"] == "# My K8s rules"

    @pytest.mark.unit
    def test_root_level_files_grouped(self) -> None:
        changes = [
            filter_mod.FileChange(path="README.md", kind=filter_mod.ChangeKind.CONTENT_DELTA),
            filter_mod.FileChange(path="AGENTS.md", kind=filter_mod.ChangeKind.CONTENT_DELTA),
        ]
        contents = {"README.md": "# Readme", "AGENTS.md": "# Agents"}
        chunks = chunked_mod.chunk_changes(changes, "james", contents)
        assert len(chunks) == 1


class TestPrompts:
    @pytest.mark.unit
    def test_onboarding_prompt_includes_both_sets(self) -> None:
        prompt = prompts_mod.build_onboarding_prompt(
            source_name="james",
            source_contents={"rules/k8s.md": "# K8s from james"},
            local_contents={"kubernetes/AGENTS.md": "# My K8s"},
        )
        assert "james" in prompt
        assert "K8s from james" in prompt
        assert "My K8s" in prompt
        assert "semantic_id" in prompt

    @pytest.mark.unit
    def test_chunk_prompt_new_files(self) -> None:
        chunk = chunked_mod.ComparisonChunk(
            source_name="james",
            changes=[filter_mod.FileChange(path="rules/new.md", kind=filter_mod.ChangeKind.NEW_FILE)],
            source_contents={"rules/new.md": "# New rule"},
        )
        prompt = prompts_mod.build_chunk_prompt(chunk)
        assert "new files" in prompt
        assert "New rule" in prompt
        assert "james" in prompt

    @pytest.mark.unit
    def test_chunk_prompt_with_local_context(self) -> None:
        chunk = chunked_mod.ComparisonChunk(
            source_name="james",
            changes=[filter_mod.FileChange(path="rules/k8s.md", kind=filter_mod.ChangeKind.CONTENT_DELTA)],
            source_contents={"rules/k8s.md": "# K8s updated"},
            local_contents={"rules/k8s.md": "# My K8s"},
        )
        prompt = prompts_mod.build_chunk_prompt(chunk)
        assert "changed files" in prompt
        assert "K8s updated" in prompt
        assert "My K8s" in prompt
        assert "related instructions" in prompt.lower()

    @pytest.mark.unit
    def test_chunk_prompt_no_local(self) -> None:
        chunk = chunked_mod.ComparisonChunk(
            source_name="james",
            changes=[filter_mod.FileChange(path="rules/new.md", kind=filter_mod.ChangeKind.NEW_FILE)],
            source_contents={"rules/new.md": "# New"},
            local_contents={"rules/new.md": None},
        )
        prompt = prompts_mod.build_chunk_prompt(chunk)
        assert "related instructions" not in prompt.lower()

    @pytest.mark.unit
    def test_onboarding_prompt_empty_local(self) -> None:
        prompt = prompts_mod.build_onboarding_prompt(
            source_name="james",
            source_contents={"rules/a.md": "# A"},
            local_contents={},
        )
        assert "No files" in prompt
