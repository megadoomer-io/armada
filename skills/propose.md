---
name: armada-propose
description: Push knowledge proposals to peers and downstream targets as PRs.
version: 0.1.0
source:
  repo: megadoomer-io/armada
  path: skills/propose.md
---

# /armada-propose — Push Proposals to Peers

Drip-feeds proposals from the queue to target repos. Each proposal becomes
a focused, individually-reviewable PR on the target's agent instructions repo.

## Workflow

### Step 1: Load config and queues

Proposal targets are **peers** (members in ≥1 group — the people you share grains
with) and **downstreams** (sink repos that receive a grain after a group
converges). Pull-only members (no group, `pull: true`) are upstreams, not
targets, and are skipped here. Each target has its own per-member/per-downstream
queue.

```python
import armada.models.config as config
import armada.models.queue as queue

cfg = config.ArmadaConfig.load()

# Peers: every member that belongs to at least one group.
peer_names = sorted({m for g in cfg.groups.values() for m in g.members})
target_names = peer_names + sorted(cfg.downstreams)

for target_name in target_names:
    q = queue.ProposalQueue.load(target_name)
    # process each target
```

### Step 1.5: Queue downstream convergence pushes

Before draining the queues, check whether any of your grains have converged.
A grain converges within a group once that group's accepted proposals reach its
threshold; at that point the grain is queued to the group's downstream sink.

First refresh the status of your outgoing proposals (a peer merging your PR means
that proposal is now `accepted`), then read convergence per grain:

```python
import armada.convergence as convergence

for sgf in <your source grain files>:
    for grain in sgf.grains:
        for push in convergence.convergence_pushes(grain, cfg):
            # push.target is a downstream name; push.group is None (sink delivery)
            q = queue.ProposalQueue.load(push.target)
            q.pending_proposals.append(
                queue.PendingProposal(
                    grain_id=grain.semantic_id,
                    description=grain.description,
                    estimated_value=queue.EstimatedValue.HIGH,
                )
            )
            q.save()
            # Record the push on the grain so convergence is idempotent — a
            # downstream that already has a proposal is never pushed again.
            grain.proposed_to.append(push)
    sgf.save()
```

`convergence_pushes` only counts accepts tagged with each group (the seam guard),
only considers groups the grain is still eligible for (retag safety), and skips a
downstream that already has a proposal (idempotency). A group without a
`convergence` block (e.g. `friends`) never produces a push.

### Step 2: For each target with pending proposals

#### 2a. Check capacity

```python
if q.at_capacity:
    # Report: "james: at capacity (3/3 open PRs), holding"
    continue
```

#### 2b. Scan for topic overlap/conflict

Before opening a new PR, check the target repo for existing PRs that
cover the same topic:

1. List open PRs on the target repo (all sources, not just Armada-labeled)
2. Ask the LLM: "Does my proposal about {grain_description} overlap or
   conflict with any of these existing PRs?"

Decision tree:
- **Overlap**: Comment on the existing PR with the complementary perspective
  instead of opening a competing PR. Update the proposal status.
- **Conflict**: Comment on the existing PR noting the alternative approach.
  Do NOT open a new PR. Mark the proposal as needing manual resolution.
- **Clear**: Proceed to open a new PR.

#### 2c. Generate and open PR

For the next pending proposal (highest priority):

1. **Read the target's repo structure** via cache clone to understand their
   conventions (file naming, directory layout, frontmatter format)

2. **Ask the LLM to adapt** the grain content to the target's structure:

   > Adapt this knowledge for {target_name}'s agent instructions repo.
   > Their structure uses: {observed conventions}.
   > Write the content as it should appear in their repo.
   > Respect their existing patterns for file naming and organization.

3. **Determine target path**: Where should this file go in the target's repo?
   The LLM decides based on the target's directory structure.

4. **Open the PR**:
   - Branch: `armada/{cfg.identity.name}/{grain_slug}`
   - Title: descriptive, based on the grain content
   - Label: `armada` (best-effort, skip if permissions deny)
   - Body: includes provenance and description

#### PR Description Format

```markdown
## Armada Proposal: {grain_description}

**Source**: @{source_user}'s agent instructions
**Grain**: {semantic_id}

### What This Adds

{LLM-generated summary of what the receiver gets}

### Provenance

This knowledge was sourced from @{source_user}'s agent instructions
and adapted to your repo's structure and conventions.

### How to Review

1. Read the proposed file for accuracy and relevance
2. Check that it fits your repo's conventions
3. Merge if useful, close with a comment if not

---
*Proposed by [Armada](https://github.com/megadoomer-io/armada)*
```

5. **Update queue state**:

```python
q.activate(
    grain_id=proposal.grain_id,
    pr_number=pr_number,
    pr_url=pr_url,
)
q.save()
```

Also update the grain's `proposed_to` list. Tag the proposal with the group it
was opened under via `cfg.proposal_group_for` — when the target is eligible via
two groups and one is convergence-bearing, this picks the convergence-bearing
one so the eventual accept counts toward the right group's threshold (and a
friends-context accept never trips the coworkers convergence):

```python
grain.proposed_to.append(
    grain_mod.GrainProposal(
        target=target_name,
        group=cfg.proposal_group_for(target_name, grain.audiences),
        pr_number=pr_number,
        pr_url=pr_url,
        status=grain_mod.ProposalStatus.OPEN,
    )
)
```

### Step 3: Report results

```
Armada Propose
──────────────
→ james:
  Opened PR #42: kdrift MCP integration for kustomize drift detection
  1 pending (pr-scan-notifications)

→ cpe-instructions:
  At capacity (3/3 open), holding
```

## Batch Size

Process up to `cfg.settings.proposal_batch_size` proposals per target
per invocation. This prevents flooding a target with too many PRs at once.

## Error Handling

- **PR creation failure** (permissions, network): Report the error, keep the
  proposal in the pending queue for retry on next invocation.
- **Label creation failure**: Log a warning, proceed without the label.
  The branch prefix `armada/` is sufficient for identification.
- **Target repo inaccessible**: Skip, report, continue with other targets.
