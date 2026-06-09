"""Tests for the unified disposition engine."""

import datetime

import pytest

import armada.disposition.engine as engine
import armada.models.grain as grain_mod


class TestDispositionMode:
    @pytest.mark.unit
    def test_decision_maps_to_grain_disposition(self) -> None:
        assert engine.DispositionDecision.INCLUDE.to_grain_disposition() == grain_mod.Disposition.INCLUDE
        assert engine.DispositionDecision.EXCLUDE.to_grain_disposition() == grain_mod.Disposition.EXCLUDE
        assert engine.DispositionDecision.DEFER.to_grain_disposition() == grain_mod.Disposition.DEFER


class TestBuildPresentation:
    @pytest.mark.unit
    def test_upstream_presentation(self) -> None:
        ctx = engine.DispositionContext(
            mode=engine.DispositionMode.UPSTREAM,
            source_name="james",
            grain_id="verify-assumptions",
            grain_description="Hypothesis-driven debugging pattern",
            source_paths=["claude/rules/workflow/verify-assumptions.md"],
            diff_summary="New file (not present locally)",
        )
        pres = engine.build_presentation(ctx)

        assert "Upstream" in pres.header
        assert "james" in pres.header
        assert "verify-assumptions" in pres.header
        assert "Hypothesis-driven" in pres.body
        assert len(pres.options) == 3
        labels = [label for _, label, _ in pres.options]
        assert "Include" in labels
        assert "Exclude" in labels
        assert "Defer" in labels

    @pytest.mark.unit
    def test_peer_presentation(self) -> None:
        ctx = engine.DispositionContext(
            mode=engine.DispositionMode.PEER,
            source_name="james",
            grain_id="kdrift-knowledge",
            grain_description="Kustomize drift detection via MCP",
        )
        pres = engine.build_presentation(ctx)

        assert "Proposal" in pres.header
        labels = [label for _, label, _ in pres.options]
        assert "Accept" in labels
        assert "Decline" in labels
        assert "Defer" in labels

    @pytest.mark.unit
    def test_presentation_includes_source_paths(self) -> None:
        ctx = engine.DispositionContext(
            mode=engine.DispositionMode.UPSTREAM,
            source_name="cerebral",
            grain_id="deployment-skill",
            grain_description="Deployment procedures",
            source_paths=["cerebral/engineering/skills/deployment/SKILL.md"],
        )
        pres = engine.build_presentation(ctx)
        assert "cerebral/engineering" in pres.body


class TestApplyDecision:
    @pytest.mark.unit
    def test_include_new_grain(self) -> None:
        sgf = grain_mod.SourceGrainFile(source="james")
        grain = engine.apply_decision(
            sgf,
            grain_id="data-safety",
            decision=engine.DispositionDecision.INCLUDE,
            description="Never delete source data without backup",
            source_paths=["claude/rules/workflow/data-safety.md"],
            local_paths=["~/.agents/rules/data-safety.md"],
        )
        assert grain.disposition == grain_mod.Disposition.INCLUDE
        assert grain.disposition_date == datetime.date.today()
        assert sgf.get_grain("data-safety") is not None

    @pytest.mark.unit
    def test_exclude_with_until(self) -> None:
        sgf = grain_mod.SourceGrainFile(source="james")
        grain = engine.apply_decision(
            sgf,
            grain_id="sudo-rule",
            decision=engine.DispositionDecision.EXCLUDE,
            description="Never use bare sudo",
            notes="Already have equivalent in GIR hooks",
            exclude_until=grain_mod.ExcludeUntil.MAJOR_CHANGE,
        )
        assert grain.disposition == grain_mod.Disposition.EXCLUDE
        assert grain.exclude_until == grain_mod.ExcludeUntil.MAJOR_CHANGE

    @pytest.mark.unit
    def test_defer(self) -> None:
        sgf = grain_mod.SourceGrainFile(source="james")
        grain = engine.apply_decision(
            sgf,
            grain_id="verify-assumptions",
            decision=engine.DispositionDecision.DEFER,
            description="Hypothesis-driven debugging",
            notes="Good pattern, not urgent",
        )
        assert grain.disposition == grain_mod.Disposition.DEFER

    @pytest.mark.unit
    def test_update_existing_grain(self) -> None:
        sgf = grain_mod.SourceGrainFile(source="james")
        engine.apply_decision(
            sgf,
            grain_id="data-safety",
            decision=engine.DispositionDecision.DEFER,
            description="Never delete source data without backup",
        )
        assert sgf.get_grain("data-safety") is not None
        assert sgf.get_grain("data-safety").disposition == grain_mod.Disposition.DEFER  # type: ignore[union-attr]

        grain = engine.apply_decision(
            sgf,
            grain_id="data-safety",
            decision=engine.DispositionDecision.INCLUDE,
            local_paths=["~/.agents/rules/data-safety.md"],
        )
        assert grain.disposition == grain_mod.Disposition.INCLUDE
        assert grain.local_paths == ["~/.agents/rules/data-safety.md"]
        assert len(sgf.grains) == 1

    @pytest.mark.unit
    def test_preserves_proposals_on_update(self) -> None:
        sgf = grain_mod.SourceGrainFile(source="james")
        sgf.upsert_grain(
            grain_mod.GrainState(
                semantic_id="data-safety",
                description="Never delete source data",
                disposition=grain_mod.Disposition.INCLUDE,
                proposed_to=[
                    grain_mod.GrainProposal(target="josh", status=grain_mod.ProposalStatus.OPEN),
                ],
            )
        )
        grain = engine.apply_decision(
            sgf,
            grain_id="data-safety",
            decision=engine.DispositionDecision.INCLUDE,
        )
        assert len(grain.proposed_to) == 1
        assert grain.proposed_to[0].target == "josh"

    @pytest.mark.unit
    def test_exclude_clears_exclude_until_on_non_exclude(self) -> None:
        sgf = grain_mod.SourceGrainFile(source="james")
        engine.apply_decision(
            sgf,
            grain_id="sudo-rule",
            decision=engine.DispositionDecision.EXCLUDE,
            exclude_until=grain_mod.ExcludeUntil.MAJOR_CHANGE,
        )
        grain = engine.apply_decision(
            sgf,
            grain_id="sudo-rule",
            decision=engine.DispositionDecision.INCLUDE,
        )
        assert grain.exclude_until is None
