# Armada

Collaborative agent knowledge network. An LLM reads two developers' agent instruction sets and proposes improvements to each via PRs.

## Quick Start

```bash
uv sync --all-groups   # Install deps
make validate           # Lint + typecheck + test
```

## Architecture

Three relationship types form a directed graph:
- **Upstream** (pull): sources you watch for knowledge to incorporate
- **Peer** (propose): bidirectional PR-based knowledge exchange
- **Downstream** (converge): targets that receive knowledge after peer consensus

### Key Concepts

- **Grain**: atomic unit of trackable knowledge, identified by LLM-assigned semantic ID (not file path)
- **Disposition**: user decision on a grain (include/exclude/defer for upstream; accept/modify/decline for peer)
- **Cache clones**: all external repos are shallow-cloned to `$XDG_CACHE_HOME/armada/repos/`, never operating on working clones

## Project Layout

```
src/armada/
  models/        # Pydantic models (config, grain state, queue state)
  git/           # Cache clone management, structural pre-filter
  disposition/   # Unified disposition engine
tests/           # pytest (unit + integration)
skills/          # Claude Code skill definitions
```

## State Layout (XDG)

```
~/.config/armada/config.yaml          # Network relationships + settings
~/.local/state/armada/grains/         # Per-source grain dispositions
~/.local/state/armada/queues/         # Per-target proposal queues
~/.local/state/armada/sync.yaml       # Last sync timestamps
~/.cache/armada/repos/                # Shallow clones
~/.cache/armada/comparisons/          # Cached LLM comparison results
```

## Conventions

- Python 3.13+, src layout, 120 char line length
- Pydantic for all config and state models
- mypy strict mode
- `uv run` for all Python commands
- Tests: `pytest` with `unit` and `integration` markers
