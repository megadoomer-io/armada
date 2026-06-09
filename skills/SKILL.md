---
name: armada
description: Collaborative agent knowledge network — sync, propose, and review agent instruction improvements across developers.
version: 0.1.0
---

# /armada — Agent Knowledge Network

Smart router for Armada operations. Detects what's needed and dispatches
to the appropriate sub-skill.

## When to Use

- Invoked explicitly by the user as `/armada` or `/armada <subcommand>`
- At session start, if `sync_check_on_session_start` is enabled in config,
  a lightweight staleness check runs (git remote refs only, no LLM calls)

## Commands

```
/armada              → status overview (pending syncs, open proposals, queue depth)
/armada sync         → pull knowledge from upstreams (see sync.md)
/armada propose      → push proposals to peers/downstreams (see propose.md)
/armada review       → handle incoming proposals on your repo (see review.md)
/armada setup        → onboarding flow (see setup.py)
/armada config       → edit network configuration
```

## Status Overview (default)

When invoked without a subcommand, present a summary:

1. **Read config** from `$XDG_CONFIG_HOME/armada/config.yaml`
   - If config doesn't exist, suggest running `/armada setup`
2. **Check sync staleness** for each upstream:
   - Read `$XDG_STATE_HOME/armada/grains/<source>.yaml`
   - Compare `last_reviewed_rev` against the remote HEAD (via cache clone fetch)
   - Report: "james: 3 changes since last sync (2 days ago)"
3. **Check proposal queues** for each peer/downstream:
   - Read `$XDG_STATE_HOME/armada/queues/<target>.yaml`
   - Report: "james: 1 open PR, 2 pending proposals"
4. **Check incoming proposals** on the user's repo:
   - Search for open PRs with `armada/` branch prefix or `armada` label
   - Report: "2 incoming proposals awaiting review"

### Output Format

```
Armada Status
─────────────
Upstreams:
  james       3 changes since last sync (2d ago)
  cerebral    up to date (synced 4h ago)

Proposals:
  → james     1 open, 2 queued
  → cpe       0 open, 1 queued

Incoming:
  2 proposals awaiting review

Run /armada sync to pull upstream changes.
```

## Config Edit

`/armada config` opens the config file path for the user and offers
guided editing:

1. Show current config summary
2. Offer to add/remove upstreams, peers, or downstreams
3. Offer to adjust settings (max_open_proposals, batch_size, etc.)
4. Write updated config

## Dependencies

- Config: `$XDG_CONFIG_HOME/armada/config.yaml` (required for all operations)
- State: `$XDG_STATE_HOME/armada/` (created on first use)
- Cache: `$XDG_CACHE_HOME/armada/repos/` (created on first sync)
- GitHub access: via MCP tools or `gh` CLI (for PR operations)

## Sub-Skills

| Skill | File | Purpose |
|-------|------|---------|
| `/armada-sync` | [sync.md](sync.md) | Pull knowledge from upstreams |
| `/armada-propose` | [propose.md](propose.md) | Push proposals to peers |
| `/armada-review` | [review.md](review.md) | Handle incoming proposals |
