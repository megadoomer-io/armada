"""Per-group convergence accounting.

A grain converges within a group when enough of that group's members accept it,
at which point the grain is proposed to the group's downstream sink. The load-
bearing correctness concern is the *convergence seam*: a member who belongs to
two groups (e.g. coworkers AND friends) has a single acceptance per proposal,
tagged with one group. A friends-context acceptance must never count toward the
coworkers' convergence threshold, or work content leaks to the shared
downstream. Counting keys strictly on ``GrainProposal.group``, which closes the
seam by construction.

Two further safety rules:

- **Retag safety:** only groups the grain is *currently* eligible for (per
  ``resolve_groups``) are counted. If a grain is retagged away from a group, its
  stale accepted proposals stop counting toward that group's threshold. Stale
  proposals are left in place and ignored, not retracted.
- **Idempotency:** a convergence push IS a ``GrainProposal`` with
  ``target == <downstream>``. A group whose downstream already has a proposal on
  the grain does not push again, so re-running convergence never opens duplicate
  downstream PRs.
"""

import armada.models.config as config
import armada.models.grain as grain


def accept_count(grain_state: grain.GrainState, group: str) -> int:
    """Count accepted proposals tagged with ``group`` on this grain.

    Keys strictly on the proposal's recorded group, so an acceptance made in a
    different group context never counts here. This equality is the convergence
    seam guard.
    """
    return sum(
        1
        for proposal in grain_state.proposed_to
        if proposal.group == group and proposal.status == grain.ProposalStatus.ACCEPTED
    )


def converged_groups(grain_state: grain.GrainState, cfg: config.ArmadaConfig) -> list[str]:
    """Eligible convergence-bearing groups whose accept count meets threshold.

    Only groups the grain is currently eligible for are considered (retag
    safety). Returned sorted for deterministic downstream ordering. Idempotency
    is NOT applied here — this reports convergence state; use
    ``convergence_pushes`` for the action.
    """
    eligible = config.resolve_groups(grain_state.audiences, cfg)
    result: list[str] = []
    for group_name in sorted(eligible):
        convergence = cfg.groups[group_name].convergence
        if convergence is None:
            continue
        if accept_count(grain_state, group_name) >= convergence.threshold:
            result.append(group_name)
    return result


def convergence_pushes(grain_state: grain.GrainState, cfg: config.ArmadaConfig) -> list[grain.GrainProposal]:
    """Downstream proposals this grain should open now (idempotent).

    For each converged group, emit a pending ``GrainProposal`` targeting the
    group's downstream, unless a proposal to that downstream already exists on
    the grain. Two groups converging to the same downstream produce a single
    push. The push carries ``group=None``: it is a sink delivery, not tied to a
    member's group context.
    """
    pushes: list[grain.GrainProposal] = []
    already_pushed_to = {proposal.target for proposal in grain_state.proposed_to}
    for group_name in converged_groups(grain_state, cfg):
        convergence = cfg.groups[group_name].convergence
        if convergence is None:  # unreachable given converged_groups; satisfies the type checker
            continue
        downstream = convergence.downstream
        if downstream in already_pushed_to:
            continue
        pushes.append(grain.GrainProposal(target=downstream, status=grain.ProposalStatus.PENDING))
        already_pushed_to.add(downstream)
    return pushes
