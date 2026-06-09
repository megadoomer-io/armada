---
name: armada
description: How the Armada agent knowledge network works - concepts, state layout, and relationship types.
version: 0.1.0
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

**Relationship types**:
- **Upstream** (pull): sources you watch. One-directional.
- **Peer** (propose): bidirectional PR-based exchange.
- **Downstream** (converge): targets that receive knowledge after
  peer consensus reaches the convergence threshold.

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
