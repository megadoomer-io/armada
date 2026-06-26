---
name: armada
description: How the Armada agent knowledge network works - concepts, state layout, groups, and audiences.
version: 0.2.0
source:
  repo: megadoomer-io/armada
  path: knowledge/KNOWLEDGE.md
---

# Armada Knowledge

Armada is a collaborative agent knowledge network. An LLM reads two
developers' agent instruction sets and proposes how each can learn
from the other, delivered as focused PRs.

## Core Concepts

**Grain**: The atomic unit of trackable knowledge. Identified by a
semantic ID assigned by the LLM (e.g., `kustomize-patch-strategy`),
not by file path. File paths are metadata that can change without
affecting grain identity.

**Disposition**: A user's decision on a grain from another source:
- **Include** (upstream) / **Accept** (peer): incorporate into my instructions
- **Exclude** / **Decline**: not relevant, don't resurface until major change
- **Defer**: relevant but not now, revisit later

**Member**: one canonical record per person (or source repo) — a repo, the
paths to watch, and a `pull` flag. A member is a **peer** (you propose to them)
if they belong to at least one group, and an **upstream** (you pull from them)
if `pull: true`. The two roles are independent: a friend can be pull-capable
without joining any sharing circle.

**Group**: a named circle of members (e.g. `coworkers`, `friends`) that acts as
a policy lens. A group gates which grains are eligible to flow to its members
and pools their accepts for convergence. It may carry a `convergence` block
(`threshold` + `downstream`); without one it is pure pairwise sharing. A group
is NOT a state partition — one person in two groups still has a single
per-member queue. The group changes eligibility and convergence accounting, not
where state lives.

**Audience**: on a grain, the list of groups it may flow to. Default `[]` means
private (shared with no one); the `"*"` sentinel means all groups. Absence never
means broadcast — sharing is opt-in, so work knowledge never leaks to the wrong
circle by omission.

**Downstream**: a sink repo that receives a grain once a group's convergence
threshold is reached (e.g. a team-shared knowledge repo).

**Convergence**: per-group consensus. When enough of a group's members accept a
grain, it is proposed to that group's downstream. Counting keys on the group a
proposal was opened under, so a grain shared with one circle never converges
through another — the same person in two groups can't have a friends-context
accept count toward the coworkers' threshold.

## State Layout

```
~/.config/armada/config.yaml           # Network relationships + settings
~/.local/state/armada/grains/*.yaml    # Per-source grain dispositions
~/.local/state/armada/queues/*.yaml    # Per-target proposal queues
~/.local/state/armada/sync.yaml        # Last sync timestamps
~/.cache/armada/repos/                 # Clones of upstream/peer repos
```

Override any path via `ARMADA_CONFIG_DIR`, `ARMADA_STATE_DIR`,
`ARMADA_CACHE_DIR` environment variables.

### Version Control Recommendation

Since Armada users already manage agent instructions in git, we
recommend version-controlling the Armada state alongside them:

- **Config** (`~/.config/armada/`): version-control. This is your
  network identity and relationship definitions.
- **State** (`~/.local/state/armada/`): version-control. Your grain
  dispositions and proposal queues are accumulated knowledge that
  took time to build.
- **Cache** (`~/.cache/armada/`): do NOT version-control. Clones
  and comparison caches are ephemeral and regenerated on demand.

The mechanism (stow, chezmoi, bare git repo, manual symlinks) is
your choice. The important thing is that config and state survive
across machines and aren't lost to a disk wipe.

## Commands

| Command | What it does |
|---------|-------------|
| `/armada` | Status overview |
| `/armada sync` | Pull changes from upstreams |
| `/armada propose` | Open PRs on peers with queued proposals |
| `/armada review` | Review incoming proposals on your repo |
| `/armada setup` | Onboarding flow |

## PR Convention

- Branch: `armada/<source-user>/<grain-slug>`
- Label: `armada` (best-effort)
- One grain per PR, max `settings.max_open_proposals` open per target
