# armada

A self-propagating knowledge network for AI agent instructions. Armada reads two developers' agent instruction sets, identifies gaps and differences, and proposes improvements to each via PRs. The network grows organically: every participant is a node in a loose, directed graph of people, teams, and instruction collections. There's no central authority, no shared canonical repo, no org chart to follow. You connect to whoever has knowledge worth watching, and they connect to you if yours is worth watching back.

Armada is its own first user. The skill files that teach your AI agent how to run Armada are themselves distributed through the Armada network. When you onboard, you get both the tool and the instructions for using it, and both stay up to date through the same sync mechanism.

## Who this is for

You manage your AI agent instructions (CLAUDE.md, AGENTS.md, rules, skills, knowledge files) in a git repository, and you want to learn from how other people configure theirs without manually reading their repos and copy-pasting.

If your agent instructions aren't in git yet, Armada isn't useful to you. Version-controlled instruction files are the unit of exchange.

## How the graph works

Three relationship types form a directed graph:

- **Upstream** (pull): sources you watch for knowledge to incorporate. One-directional. You learn from them; they don't need to know you exist.
- **Peer** (propose): bidirectional PR-based knowledge exchange. You send proposals to each other. This is the collaborative part.
- **Downstream** (converge): targets that receive knowledge after multiple peers agree on it. Useful for team-shared instruction sets that should only adopt changes with consensus.

Each person's config file declares their own edges in the graph. There's no global registry. The network topology emerges from individual decisions about who to watch and who to exchange with.

## Onboarding

### Option A: Someone you know already uses Armada

The easiest path. Ask them to run `/armada propose` with your repo as a peer target. You'll get a PR on your agent instructions repo containing the Armada skill files and a starter config. Review it, merge it, and you're in the network.

This is the curated path: a human you trust reviewed what to send you, and you review what to accept. Slow, deliberate, and low-risk.

### Option B: Self-service

If you don't know anyone using Armada yet (or prefer to set things up yourself):

1. **Install the skill** into your Claude Code skills directory:
   ```bash
   # Clone into your skills
   git clone https://github.com/megadoomer-io/armada.git ~/.claude/skills/armada
   ```

2. **Run setup**:
   ```
   /armada setup
   ```
   This walks you through creating your config: who you are, where your agent instructions repo lives, and which sources to watch.

3. **Add an upstream** to start pulling knowledge from someone:
   ```
   /armada config
   ```
   Add any public agent instructions repo as an upstream. You don't need their permission to watch.

4. **Run your first sync**:
   ```
   /armada sync
   ```
   Armada reads the upstream's instruction set, compares it to yours, identifies knowledge you're missing, and presents each piece for your decision: include, exclude, or defer.

## What a sync looks like

When you run `/armada sync`, the LLM reads both instruction sets and identifies atomic pieces of knowledge called **grains**. Each grain gets a semantic ID (like `kdrift-mcp-integration` or `pre-commit-hook-config`) that tracks it across file renames and restructuring.

For each grain you don't have, you choose:
- **Include**: adapt the knowledge to your repo's structure and conventions, commit it
- **Exclude**: not relevant to you, don't surface it again (until the source changes it)
- **Defer**: interesting but not now, remind me next sync

Your decisions persist in state files, so future syncs only surface new or changed knowledge.

## State layout

Armada follows XDG conventions. Everything is local to your machine.

```
~/.config/armada/config.yaml          # Your network edges and settings
~/.local/state/armada/grains/         # Your decisions on each grain
~/.local/state/armada/queues/         # Outbound proposal queue
~/.local/state/armada/sync.yaml       # Last sync timestamps
~/.cache/armada/repos/                # Clones of upstream/peer repos (safe to delete)
```

Config and state are worth version-controlling. Cache is disposable.

## Development

```bash
uv sync --all-groups   # Install deps
make validate           # Lint + typecheck + test
```

Python 3.13+, src layout, mypy strict, 120 char lines.

## License

[Beer-Ware](LICENSE) (Revision 42). If we meet some day and you think this stuff is worth it, you can buy me a beer in return.
