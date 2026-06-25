"""Tests for Armada Pydantic models."""

import datetime
import pathlib
import textwrap

import pydantic
import pytest
import yaml

import armada.models.config as config_mod
import armada.models.grain as grain_mod
import armada.models.queue as queue_mod

SAMPLE_CONFIG_YAML = textwrap.dedent("""\
    version: 2
    identity:
      name: mikedougherty
      repo: mikedougherty/dotfiles
      agent_root: ~/.agents/
    members:
      james:
        repo: jameshounshell/dotfiles
        paths: [claude/]
        pull: true
      josh:
        repo: missionlane-scratch/jhoover
        paths: [AGENTS.md, github/]
      cerebral:
        repo: missionlane/cerebral
        paths: [cerebral/engineering/]
        pull: true
    groups:
      coworkers:
        members: [james, josh]
        convergence:
          threshold: 2
          downstream: cpe
      friends:
        members: [james]
    downstreams:
      cpe:
        repo: missionlane-scratch/cpe-agent-knowledge
        paths: [knowledge/, skills/, rules/]
    settings:
      max_open_proposals: 3
      sync_check_on_session_start: true
      proposal_batch_size: 2
      auto_fetch_interval: daily
    preferences:
      github_client: mcp
""")


def sample_config() -> config_mod.ArmadaConfig:
    return config_mod.ArmadaConfig.model_validate(yaml.safe_load(SAMPLE_CONFIG_YAML))


class TestArmadaConfig:
    @pytest.mark.unit
    def test_parse_full_config(self) -> None:
        cfg = sample_config()

        assert cfg.version == 2
        assert cfg.identity.name == "mikedougherty"
        assert cfg.identity.repo == "mikedougherty/dotfiles"

        assert set(cfg.members) == {"james", "josh", "cerebral"}
        assert cfg.members["james"].repo == "jameshounshell/dotfiles"
        assert cfg.members["james"].paths == ["claude/"]
        assert cfg.members["james"].pull is True
        assert cfg.members["josh"].pull is False

        assert set(cfg.groups) == {"coworkers", "friends"}
        assert cfg.groups["coworkers"].members == ["james", "josh"]
        assert cfg.groups["coworkers"].convergence is not None
        assert cfg.groups["coworkers"].convergence.threshold == 2
        assert cfg.groups["coworkers"].convergence.downstream == "cpe"
        assert cfg.groups["friends"].convergence is None

        assert set(cfg.downstreams) == {"cpe"}
        assert cfg.downstreams["cpe"].repo == "missionlane-scratch/cpe-agent-knowledge"

        assert cfg.settings.max_open_proposals == 3
        assert cfg.preferences.github_client == "mcp"

    @pytest.mark.unit
    def test_defaults(self) -> None:
        cfg = config_mod.ArmadaConfig(
            identity=config_mod.Identity(name="test", repo="org/repo"),
        )
        assert cfg.version == 2
        assert cfg.members == {}
        assert cfg.groups == {}
        assert cfg.downstreams == {}
        assert cfg.settings.max_open_proposals == 3
        assert cfg.settings.auto_fetch_interval == "daily"

    @pytest.mark.unit
    def test_agent_root_expands_home(self) -> None:
        identity = config_mod.Identity(name="test", repo="org/repo", agent_root="~/.agents/")
        assert "~" not in str(identity.agent_root)
        assert identity.agent_root.is_absolute()

    @pytest.mark.unit
    def test_roundtrip_yaml(self, xdg_dirs: dict[str, pathlib.Path]) -> None:
        cfg = sample_config()
        config_path = xdg_dirs["config"] / "config.yaml"
        cfg.save(config_path)
        loaded = config_mod.ArmadaConfig.load(config_path)
        assert loaded.version == 2
        assert loaded.identity.name == cfg.identity.name
        assert set(loaded.members) == set(cfg.members)
        assert loaded.members["james"].pull is True
        assert loaded.groups["coworkers"].convergence is not None
        assert loaded.groups["coworkers"].convergence.downstream == "cpe"
        assert loaded.settings.max_open_proposals == cfg.settings.max_open_proposals

    @pytest.mark.unit
    def test_extra_preferences_allowed(self) -> None:
        data = yaml.safe_load(SAMPLE_CONFIG_YAML)
        data["preferences"]["jira_client"] = "mcp"
        data["preferences"]["slack_client"] = "mcp"
        cfg = config_mod.ArmadaConfig.model_validate(data)
        assert cfg.preferences.github_client == "mcp"
        assert cfg.preferences.model_extra["jira_client"] == "mcp"  # type: ignore[union-attr]

    @pytest.mark.unit
    def test_rejects_version_1(self) -> None:
        data = yaml.safe_load(SAMPLE_CONFIG_YAML)
        data["version"] = 1
        with pytest.raises(pydantic.ValidationError, match="unsupported config version"):
            config_mod.ArmadaConfig.model_validate(data)


class TestModelValidator:
    @pytest.mark.unit
    def test_dangling_member_reference(self) -> None:
        data = yaml.safe_load(SAMPLE_CONFIG_YAML)
        data["groups"]["coworkers"]["members"].append("ghost")
        with pytest.raises(pydantic.ValidationError, match="undefined member 'ghost'"):
            config_mod.ArmadaConfig.model_validate(data)

    @pytest.mark.unit
    def test_dangling_downstream_reference(self) -> None:
        data = yaml.safe_load(SAMPLE_CONFIG_YAML)
        data["groups"]["coworkers"]["convergence"]["downstream"] = "ghost"
        with pytest.raises(pydantic.ValidationError, match="undefined downstream 'ghost'"):
            config_mod.ArmadaConfig.model_validate(data)

    @pytest.mark.unit
    def test_member_in_two_convergence_groups_rejected(self) -> None:
        # james is in coworkers (convergence) and friends; give friends a
        # convergence block too, so james would be in two convergence-bearing
        # groups -> the scalar GrainProposal.group would be ambiguous.
        data = yaml.safe_load(SAMPLE_CONFIG_YAML)
        data["groups"]["friends"]["convergence"] = {"threshold": 2, "downstream": "cpe"}
        with pytest.raises(
            pydantic.ValidationError,
            match="multiple convergence-bearing groups",
        ):
            config_mod.ArmadaConfig.model_validate(data)

    @pytest.mark.unit
    def test_member_in_two_non_convergence_groups_allowed(self) -> None:
        # james in coworkers (convergence) + friends (no convergence) is fine —
        # this is the overlap case the whole design exists to support.
        cfg = sample_config()
        assert "james" in cfg.groups["coworkers"].members
        assert "james" in cfg.groups["friends"].members


class TestPullMembers:
    @pytest.mark.unit
    def test_pull_members_filters_by_flag(self) -> None:
        cfg = sample_config()
        assert set(cfg.pull_members) == {"james", "cerebral"}
        assert "josh" not in cfg.pull_members

    @pytest.mark.unit
    def test_pull_only_member_in_no_groups(self) -> None:
        # cerebral is pull: true but belongs to no group: a valid upstream-only
        # entry (pulled from, proposes to nobody).
        cfg = sample_config()
        assert "cerebral" in cfg.pull_members
        assert all("cerebral" not in g.members for g in cfg.groups.values())


class TestResolveGroups:
    @pytest.mark.unit
    def test_identity_map(self) -> None:
        cfg = sample_config()
        assert config_mod.resolve_groups(["coworkers"], cfg) == {"coworkers"}
        assert config_mod.resolve_groups(["coworkers", "friends"], cfg) == {"coworkers", "friends"}

    @pytest.mark.unit
    def test_empty_is_private(self) -> None:
        cfg = sample_config()
        assert config_mod.resolve_groups([], cfg) == set()

    @pytest.mark.unit
    def test_star_expands_to_all_groups(self) -> None:
        cfg = sample_config()
        assert config_mod.resolve_groups(["*"], cfg) == {"coworkers", "friends"}

    @pytest.mark.unit
    def test_unknown_group_dropped(self) -> None:
        cfg = sample_config()
        assert config_mod.resolve_groups(["nonexistent"], cfg) == set()
        assert config_mod.resolve_groups(["coworkers", "nonexistent"], cfg) == {"coworkers"}


class TestProposalGroupFor:
    @pytest.mark.unit
    def test_convergence_bearing_wins_for_dual_group_member(self) -> None:
        # james is in coworkers (convergence) and friends; a grain eligible for
        # both must tag the proposal with coworkers so the accept counts toward
        # convergence and a friends-context accept never leaks into cpe.
        cfg = sample_config()
        assert cfg.proposal_group_for("james", ["coworkers", "friends"]) == "coworkers"
        assert cfg.proposal_group_for("james", ["*"]) == "coworkers"

    @pytest.mark.unit
    def test_non_convergence_group_when_only_eligible(self) -> None:
        cfg = sample_config()
        assert cfg.proposal_group_for("james", ["friends"]) == "friends"

    @pytest.mark.unit
    def test_member_not_eligible_returns_none(self) -> None:
        cfg = sample_config()
        # josh is not in friends.
        assert cfg.proposal_group_for("josh", ["friends"]) is None
        # empty audiences -> private -> no eligible group.
        assert cfg.proposal_group_for("james", []) is None
        # audience names an unknown group -> dropped -> no eligible group.
        assert cfg.proposal_group_for("james", ["nonexistent"]) is None


class TestAudiences:
    @pytest.mark.unit
    def test_default_empty_private(self) -> None:
        grain = grain_mod.GrainState(semantic_id="x")
        assert grain.audiences == []

    @pytest.mark.unit
    def test_star_sentinel_allowed_alone(self) -> None:
        grain = grain_mod.GrainState(semantic_id="x", audiences=["*"])
        assert grain.audiences == ["*"]

    @pytest.mark.unit
    def test_named_groups_allowed(self) -> None:
        grain = grain_mod.GrainState(semantic_id="x", audiences=["coworkers", "friends"])
        assert grain.audiences == ["coworkers", "friends"]

    @pytest.mark.unit
    def test_star_mixed_with_named_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="cannot be combined"):
            grain_mod.GrainState(semantic_id="x", audiences=["*", "coworkers"])


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
        sgf.upsert_grain(grain_mod.GrainState(semantic_id="verify-assumptions", description="x"))
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
                audiences=["coworkers"],
                source_paths=["claude/rules/workflow/data-safety.md"],
                local_paths=["~/.agents/rules/data-safety.md"],
                proposed_to=[
                    grain_mod.GrainProposal(
                        target="james",
                        group="coworkers",
                        status=grain_mod.ProposalStatus.OPEN,
                    ),
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
        assert grain.audiences == ["coworkers"]
        assert grain.disposition == grain_mod.Disposition.INCLUDE
        assert len(grain.proposed_to) == 1
        assert grain.proposed_to[0].target == "james"
        assert grain.proposed_to[0].group == "coworkers"

    @pytest.mark.unit
    def test_grain_proposal_group_defaults_none(self) -> None:
        proposal = grain_mod.GrainProposal(target="james")
        assert proposal.group is None

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
            queue_mod.PendingProposal(grain_id="kdrift-knowledge", description="kdrift MCP"),
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
