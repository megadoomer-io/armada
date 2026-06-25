"""Tests for per-group convergence accounting, including the convergence seam."""

import pytest

import armada.convergence as convergence
import armada.models.config as config_mod
import armada.models.grain as grain_mod


def make_config() -> config_mod.ArmadaConfig:
    """james is in coworkers (convergence, threshold 2 -> cpe) AND friends (no
    convergence). josh is in coworkers only. This is the overlap topology the
    seam test exercises."""
    return config_mod.ArmadaConfig(
        identity=config_mod.Identity(name="mikedougherty", repo="mikedougherty/dotfiles"),
        members={
            "james": config_mod.Member(repo="jameshounshell/dotfiles"),
            "josh": config_mod.Member(repo="missionlane-scratch/jhoover"),
        },
        groups={
            "coworkers": config_mod.Group(
                members=["james", "josh"],
                convergence=config_mod.Convergence(threshold=2, downstream="cpe"),
            ),
            "friends": config_mod.Group(members=["james"]),
        },
        downstreams={
            "cpe": config_mod.Downstream(repo="missionlane-scratch/cpe-agent-knowledge"),
        },
    )


def accepted(target: str, group: str | None) -> grain_mod.GrainProposal:
    return grain_mod.GrainProposal(
        target=target,
        group=group,
        status=grain_mod.ProposalStatus.ACCEPTED,
    )


class TestAcceptCount:
    @pytest.mark.unit
    def test_counts_only_matching_group_and_accepted(self) -> None:
        grain = grain_mod.GrainState(
            semantic_id="g",
            audiences=["coworkers"],
            proposed_to=[
                accepted("josh", "coworkers"),
                accepted("james", "friends"),  # different group context
                grain_mod.GrainProposal(
                    target="james", group="coworkers", status=grain_mod.ProposalStatus.OPEN
                ),  # not accepted
            ],
        )
        assert convergence.accept_count(grain, "coworkers") == 1
        assert convergence.accept_count(grain, "friends") == 1


class TestConvergenceSeam:
    @pytest.mark.unit
    def test_friends_accept_does_not_trip_coworkers(self) -> None:
        # THE SEAM. james accepts in the friends context; josh accepts in
        # coworkers. coworkers needs 2 accepts, but james's friends-context
        # accept must not count -> only josh -> below threshold -> no push.
        cfg = make_config()
        grain = grain_mod.GrainState(
            semantic_id="kdrift-knowledge",
            audiences=["coworkers", "friends"],
            proposed_to=[
                accepted("james", "friends"),
                accepted("josh", "coworkers"),
            ],
        )
        assert convergence.accept_count(grain, "coworkers") == 1
        assert convergence.converged_groups(grain, cfg) == []
        assert convergence.convergence_pushes(grain, cfg) == []

    @pytest.mark.unit
    def test_coworkers_converges_when_both_accept_in_context(self) -> None:
        # Now james ALSO accepts in the coworkers context. Two coworkers
        # accepts -> threshold met -> push to cpe.
        cfg = make_config()
        grain = grain_mod.GrainState(
            semantic_id="kdrift-knowledge",
            audiences=["coworkers", "friends"],
            proposed_to=[
                accepted("james", "coworkers"),
                accepted("josh", "coworkers"),
            ],
        )
        assert convergence.converged_groups(grain, cfg) == ["coworkers"]
        pushes = convergence.convergence_pushes(grain, cfg)
        assert len(pushes) == 1
        assert pushes[0].target == "cpe"
        assert pushes[0].group is None
        assert pushes[0].status == grain_mod.ProposalStatus.PENDING


class TestThreshold:
    @pytest.mark.unit
    def test_below_threshold_no_push(self) -> None:
        cfg = make_config()
        grain = grain_mod.GrainState(
            semantic_id="g",
            audiences=["coworkers"],
            proposed_to=[accepted("james", "coworkers")],
        )
        assert convergence.convergence_pushes(grain, cfg) == []

    @pytest.mark.unit
    def test_non_convergence_group_never_pushes(self) -> None:
        # friends has no convergence block; any number of friends accepts never
        # produces a downstream push.
        cfg = make_config()
        grain = grain_mod.GrainState(
            semantic_id="g",
            audiences=["friends"],
            proposed_to=[accepted("james", "friends")],
        )
        assert convergence.converged_groups(grain, cfg) == []
        assert convergence.convergence_pushes(grain, cfg) == []


class TestRetagSafety:
    @pytest.mark.unit
    def test_stale_accepts_stop_counting_after_retag(self) -> None:
        # Grain once tagged coworkers reached 2 coworkers accepts, then was
        # retagged to friends only. coworkers is no longer eligible, so the
        # stale accepts no longer count -> no push. The proposals are left in
        # place, not retracted.
        cfg = make_config()
        grain = grain_mod.GrainState(
            semantic_id="g",
            audiences=["friends"],
            proposed_to=[
                accepted("james", "coworkers"),
                accepted("josh", "coworkers"),
            ],
        )
        assert convergence.converged_groups(grain, cfg) == []
        assert convergence.convergence_pushes(grain, cfg) == []


class TestIdempotency:
    @pytest.mark.unit
    def test_no_repush_when_downstream_proposal_exists(self) -> None:
        # Threshold met, but a proposal to cpe already exists (a prior
        # convergence push). Re-running must not open a duplicate.
        cfg = make_config()
        grain = grain_mod.GrainState(
            semantic_id="g",
            audiences=["coworkers"],
            proposed_to=[
                accepted("james", "coworkers"),
                accepted("josh", "coworkers"),
                grain_mod.GrainProposal(target="cpe", pr_number=7, status=grain_mod.ProposalStatus.OPEN),
            ],
        )
        # Still reports converged (state), but produces no new push (action).
        assert convergence.converged_groups(grain, cfg) == ["coworkers"]
        assert convergence.convergence_pushes(grain, cfg) == []

    @pytest.mark.unit
    def test_two_groups_same_downstream_pushes_once(self) -> None:
        # Two convergence-bearing groups (disjoint members, so invariant (c)
        # holds) both target cpe and both converge. The grain should be pushed
        # to cpe once, not twice.
        cfg = config_mod.ArmadaConfig(
            identity=config_mod.Identity(name="me", repo="me/dotfiles"),
            members={
                "a": config_mod.Member(repo="a/r"),
                "b": config_mod.Member(repo="b/r"),
            },
            groups={
                "g1": config_mod.Group(
                    members=["a"],
                    convergence=config_mod.Convergence(threshold=1, downstream="cpe"),
                ),
                "g2": config_mod.Group(
                    members=["b"],
                    convergence=config_mod.Convergence(threshold=1, downstream="cpe"),
                ),
            },
            downstreams={"cpe": config_mod.Downstream(repo="org/cpe")},
        )
        grain = grain_mod.GrainState(
            semantic_id="g",
            audiences=["g1", "g2"],
            proposed_to=[accepted("a", "g1"), accepted("b", "g2")],
        )
        assert convergence.converged_groups(grain, cfg) == ["g1", "g2"]
        pushes = convergence.convergence_pushes(grain, cfg)
        assert len(pushes) == 1
        assert pushes[0].target == "cpe"
