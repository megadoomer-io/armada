"""Tests for Armada Pydantic models."""

import datetime
import pathlib
import textwrap

import pytest
import yaml

import armada.models.config as config_mod
import armada.models.grain as grain_mod
import armada.models.queue as queue_mod

SAMPLE_CONFIG_YAML = textwrap.dedent("""\
    version: 1
    identity:
      name: mikedougherty
      repo: missionlane-scratch/mcd-agent-instructions
      agent_root: ~/.agents/
    upstreams:
      - name: james
        repo: missionlane-scratch/hounshell-dotfiles
        paths: [claude/]
      - name: cerebral
        repo: missionlane/cerebral
        paths: [cerebral/engineering/]
    peers:
      - name: james
        repo: missionlane-scratch/hounshell-dotfiles
        paths: [claude/]
    downstreams:
      - name: cpe-instructions
        repo: missionlane-scratch/cpe-agent-instructions
        convergence_threshold: 2
    settings:
      max_open_proposals: 3
      sync_check_on_session_start: true
      proposal_batch_size: 2
      auto_fetch_interval: daily
    preferences:
      github_client: mcp
""")


class TestArmadaConfig:
    @pytest.mark.unit
    def test_parse_full_config(self) -> None:
        data = yaml.safe_load(SAMPLE_CONFIG_YAML)
        cfg = config_mod.ArmadaConfig.model_validate(data)

        assert cfg.version == 1
        assert cfg.identity.name == "mikedougherty"
        assert cfg.identity.repo == "missionlane-scratch/mcd-agent-instructions"
        assert len(cfg.upstreams) == 2
        assert cfg.upstreams[0].name == "james"
        assert cfg.upstreams[0].paths == ["claude/"]
        assert len(cfg.peers) == 1
        assert cfg.peers[0].name == "james"
        assert len(cfg.downstreams) == 1
        assert cfg.downstreams[0].convergence_threshold == 2
        assert cfg.settings.max_open_proposals == 3
        assert cfg.preferences.github_client == "mcp"

    @pytest.mark.unit
    def test_defaults(self) -> None:
        cfg = config_mod.ArmadaConfig(
            identity=config_mod.Identity(
                name="test",
                repo="org/repo",
            )
        )
        assert cfg.version == 1
        assert cfg.upstreams == []
        assert cfg.peers == []
        assert cfg.downstreams == []
        assert cfg.settings.max_open_proposals == 3
        assert cfg.settings.auto_fetch_interval == "daily"

    @pytest.mark.unit
    def test_agent_root_expands_home(self) -> None:
        identity = config_mod.Identity(
            name="test",
            repo="org/repo",
            agent_root="~/.agents/",
        )
        assert "~" not in str(identity.agent_root)
        assert identity.agent_root.is_absolute()

    @pytest.mark.unit
    def test_roundtrip_yaml(self, xdg_dirs: dict[str, pathlib.Path]) -> None:
        data = yaml.safe_load(SAMPLE_CONFIG_YAML)
        cfg = config_mod.ArmadaConfig.model_validate(data)
        config_path = xdg_dirs["config"] / "config.yaml"
        cfg.save(config_path)
        loaded = config_mod.ArmadaConfig.load(config_path)
        assert loaded.identity.name == cfg.identity.name
        assert len(loaded.upstreams) == len(cfg.upstreams)
        assert loaded.settings.max_open_proposals == cfg.settings.max_open_proposals

    @pytest.mark.unit
    def test_extra_preferences_allowed(self) -> None:
        data = yaml.safe_load(SAMPLE_CONFIG_YAML)
        data["preferences"]["jira_client"] = "mcp"
        data["preferences"]["slack_client"] = "mcp"
        cfg = config_mod.ArmadaConfig.model_validate(data)
        assert cfg.preferences.github_client == "mcp"
        assert cfg.preferences.model_extra["jira_client"] == "mcp"  # type: ignore[union-attr]


class TestDirectoryResolvers:
    @pytest.mark.unit
    def test_config_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARMADA_CONFIG_DIR", "/tmp/armada-test-config")
        assert config_mod.config_dir() == pathlib.Path("/tmp/armada-test-config")

    @pytest.mark.unit
    def test_state_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARMADA_STATE_DIR", "/tmp/armada-test-state")
        assert config_mod.state_dir() == pathlib.Path("/tmp/armada-test-state")

    @pytest.mark.unit
    def test_cache_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARMADA_CACHE_DIR", "/tmp/armada-test-cache")
        assert config_mod.cache_dir() == pathlib.Path("/tmp/armada-test-cache")

    @pytest.mark.unit
    def test_config_dir_xdg_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARMADA_CONFIG_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg-config")
        assert config_mod.config_dir() == pathlib.Path("/tmp/xdg-config/armada")

    @pytest.mark.unit
    def test_config_dir_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ARMADA_CONFIG_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = config_mod.config_dir()
        assert result.name == "armada"
        assert ".config" in str(result)


class TestGrainState:
    @pytest.mark.unit
    def test_create_grain(self) -> None:
        grain = grain_mod.GrainState(
            semantic_id="kustomize-patch-strategy",
            description="Strategic merge vs JSON 6902 patch patterns",
            disposition=grain_mod.Disposition.INCLUDE,
            disposition_date=datetime.date(2026, 5, 14),
            source_paths=["claude/rules/kubernetes/kustomize-patches.md"],
            local_paths=["~/.agents/knowledge/kustomize-patterns/KNOWLEDGE.md"],
        )
        assert grain.semantic_id == "kustomize-patch-strategy"
        assert grain.disposition == grain_mod.Disposition.INCLUDE

    @pytest.mark.unit
    def test_source_grain_file_upsert(self) -> None:
        sgf = grain_mod.SourceGrainFile(source="james")
        grain1 = grain_mod.GrainState(
            semantic_id="verify-assumptions",
            description="Hypothesis-driven debugging",
        )
        sgf.upsert_grain(grain1)
        assert len(sgf.grains) == 1

        updated = grain_mod.GrainState(
            semantic_id="verify-assumptions",
            description="Updated description",
            disposition=grain_mod.Disposition.INCLUDE,
        )
        sgf.upsert_grain(updated)
        assert len(sgf.grains) == 1
        assert sgf.grains[0].description == "Updated description"
        assert sgf.grains[0].disposition == grain_mod.Disposition.INCLUDE

    @pytest.mark.unit
    def test_source_grain_file_get(self) -> None:
        sgf = grain_mod.SourceGrainFile(source="james")
        sgf.upsert_grain(grain_mod.GrainState(semantic_id="a", description="A"))
        sgf.upsert_grain(grain_mod.GrainState(semantic_id="b", description="B"))

        assert sgf.get_grain("a") is not None
        assert sgf.get_grain("a").description == "A"  # type: ignore[union-attr]
        assert sgf.get_grain("nonexistent") is None

    @pytest.mark.unit
    def test_grain_file_roundtrip(self, xdg_dirs: dict[str, pathlib.Path]) -> None:
        sgf = grain_mod.SourceGrainFile(
            source="james",
            last_reviewed_rev="abc1234",
            current_rev="def5678",
        )
        sgf.upsert_grain(
            grain_mod.GrainState(
                semantic_id="data-safety",
                description="Never delete source data without backup",
                disposition=grain_mod.Disposition.INCLUDE,
                disposition_date=datetime.date(2026, 5, 14),
                source_paths=["claude/rules/workflow/data-safety.md"],
                local_paths=["~/.agents/rules/data-safety.md"],
                proposed_to=[
                    grain_mod.GrainProposal(target="josh", status=grain_mod.ProposalStatus.PENDING),
                ],
            )
        )
        state_path = xdg_dirs["state"] / "grains" / "james.yaml"
        sgf.save(state_path)

        loaded = grain_mod.SourceGrainFile.load("james", state_path)
        assert loaded.source == "james"
        assert loaded.last_reviewed_rev == "abc1234"
        assert len(loaded.grains) == 1
        grain = loaded.grains[0]
        assert grain.semantic_id == "data-safety"
        assert grain.disposition == grain_mod.Disposition.INCLUDE
        assert len(grain.proposed_to) == 1
        assert grain.proposed_to[0].target == "josh"

    @pytest.mark.unit
    def test_grain_file_load_missing(self, xdg_dirs: dict[str, pathlib.Path]) -> None:
        state_path = xdg_dirs["state"] / "grains" / "nonexistent.yaml"
        sgf = grain_mod.SourceGrainFile.load("nonexistent", state_path)
        assert sgf.source == "nonexistent"
        assert sgf.grains == []

    @pytest.mark.unit
    def test_exclude_until(self) -> None:
        grain = grain_mod.GrainState(
            semantic_id="sudo-rule",
            description="Never use bare sudo",
            disposition=grain_mod.Disposition.EXCLUDE,
            exclude_until=grain_mod.ExcludeUntil.MAJOR_CHANGE,
        )
        assert grain.exclude_until == grain_mod.ExcludeUntil.MAJOR_CHANGE


class TestProposalQueue:
    @pytest.mark.unit
    def test_empty_queue(self) -> None:
        q = queue_mod.ProposalQueue(target="james")
        assert q.open_count == 0
        assert not q.at_capacity
        assert q.get_next_pending() is None

    @pytest.mark.unit
    def test_capacity_tracking(self) -> None:
        q = queue_mod.ProposalQueue(target="james", max_open=2)
        q.active_proposals = [
            queue_mod.ActiveProposal(
                grain_id="a",
                pr_number=1,
                pr_url="https://github.com/test/1",
                opened=datetime.date(2026, 6, 1),
                status="open",
            ),
            queue_mod.ActiveProposal(
                grain_id="b",
                pr_number=2,
                pr_url="https://github.com/test/2",
                opened=datetime.date(2026, 6, 1),
                status="open",
            ),
        ]
        assert q.open_count == 2
        assert q.at_capacity

    @pytest.mark.unit
    def test_closed_prs_dont_count(self) -> None:
        q = queue_mod.ProposalQueue(target="james", max_open=2)
        q.active_proposals = [
            queue_mod.ActiveProposal(
                grain_id="a",
                pr_number=1,
                pr_url="https://github.com/test/1",
                opened=datetime.date(2026, 6, 1),
                status="merged",
            ),
            queue_mod.ActiveProposal(
                grain_id="b",
                pr_number=2,
                pr_url="https://github.com/test/2",
                opened=datetime.date(2026, 6, 1),
                status="open",
            ),
        ]
        assert q.open_count == 1
        assert not q.at_capacity

    @pytest.mark.unit
    def test_priority_ordering(self) -> None:
        q = queue_mod.ProposalQueue(target="james")
        q.pending_proposals = [
            queue_mod.PendingProposal(grain_id="low", priority=queue_mod.ProposalPriority.LOW),
            queue_mod.PendingProposal(grain_id="high", priority=queue_mod.ProposalPriority.HIGH),
            queue_mod.PendingProposal(grain_id="med", priority=queue_mod.ProposalPriority.MEDIUM),
        ]
        nxt = q.get_next_pending()
        assert nxt is not None
        assert nxt.grain_id == "high"

    @pytest.mark.unit
    def test_activate_proposal(self) -> None:
        q = queue_mod.ProposalQueue(target="james")
        q.pending_proposals = [
            queue_mod.PendingProposal(
                grain_id="kdrift-knowledge",
                description="kdrift MCP integration",
            ),
        ]
        q.activate("kdrift-knowledge", pr_number=42, pr_url="https://github.com/test/42")
        assert len(q.pending_proposals) == 0
        assert len(q.active_proposals) == 1
        assert q.active_proposals[0].pr_number == 42
        assert q.active_proposals[0].status == "open"

    @pytest.mark.unit
    def test_queue_roundtrip(self, xdg_dirs: dict[str, pathlib.Path]) -> None:
        q = queue_mod.ProposalQueue(target="james", max_open=3)
        q.active_proposals = [
            queue_mod.ActiveProposal(
                grain_id="event-bus",
                pr_number=42,
                pr_url="https://github.com/test/42",
                opened=datetime.date(2026, 6, 10),
            ),
        ]
        q.pending_proposals = [
            queue_mod.PendingProposal(
                grain_id="kdrift-knowledge",
                priority=queue_mod.ProposalPriority.HIGH,
                description="kdrift MCP integration",
                estimated_value=queue_mod.EstimatedValue.HIGH,
            ),
        ]
        queue_path = xdg_dirs["state"] / "queues" / "james.yaml"
        q.save(queue_path)

        loaded = queue_mod.ProposalQueue.load("james", queue_path)
        assert loaded.target == "james"
        assert len(loaded.active_proposals) == 1
        assert loaded.active_proposals[0].grain_id == "event-bus"
        assert len(loaded.pending_proposals) == 1
        assert loaded.pending_proposals[0].grain_id == "kdrift-knowledge"

    @pytest.mark.unit
    def test_queue_load_missing(self, xdg_dirs: dict[str, pathlib.Path]) -> None:
        queue_path = xdg_dirs["state"] / "queues" / "nonexistent.yaml"
        q = queue_mod.ProposalQueue.load("nonexistent", queue_path)
        assert q.target == "nonexistent"
        assert q.active_proposals == []
