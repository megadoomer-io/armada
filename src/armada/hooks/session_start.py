#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "pyyaml",
# ]
# ///
"""SessionStart hook: check Armada upstream staleness.

Compares each upstream's remote HEAD against the last reviewed revision.
Outputs a one-line notification if any upstream has new changes.
Fast: uses git ls-remote (no clone, no fetch, no LLM).

Exits silently (no output) when:
- No Armada config exists
- sync_check_on_session_start is false
- All upstreams are up to date
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def config_dir() -> Path:
    if env := os.environ.get("ARMADA_CONFIG_DIR"):
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", "~/.config")
    return Path(xdg).expanduser() / "armada"


def state_dir() -> Path:
    if env := os.environ.get("ARMADA_STATE_DIR"):
        return Path(env)
    xdg = os.environ.get("XDG_STATE_HOME", "~/.local/state")
    return Path(xdg).expanduser() / "armada"


def repo_to_url(repo: str) -> str:
    if repo.startswith(("https://", "git@", "ssh://", "/")):
        return repo
    return f"https://github.com/{repo}.git"


def get_remote_head(repo_url: str) -> str | None:
    """Get the remote HEAD SHA via ls-remote. Returns None on failure."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        parts = result.stdout.strip().split()
        return parts[0] if parts else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def check_staleness() -> str | None:
    """Check all upstreams for changes. Returns notification text or None."""
    cfg_path = config_dir() / "config.yaml"
    if not cfg_path.exists():
        return None

    try:
        config = yaml.safe_load(cfg_path.read_text())
    except (yaml.YAMLError, OSError):
        return None

    if not config:
        return None

    settings = config.get("settings", {})
    if not settings.get("sync_check_on_session_start", True):
        return None

    upstreams = config.get("upstreams", [])
    if not upstreams:
        return None

    stale_sources: list[tuple[str, int]] = []

    for upstream in upstreams:
        name = upstream.get("name", "unknown")
        repo = upstream.get("repo", "")
        if not repo:
            continue

        grain_path = state_dir() / "grains" / f"{name}.yaml"
        last_rev = None
        if grain_path.exists():
            try:
                grain_data = yaml.safe_load(grain_path.read_text())
                last_rev = grain_data.get("last_reviewed_rev") if grain_data else None
            except (yaml.YAMLError, OSError):
                pass

        remote_head = get_remote_head(repo_to_url(repo))
        if remote_head is None:
            continue

        if last_rev is None:
            stale_sources.append((name, -1))
        elif remote_head != last_rev:
            stale_sources.append((name, 1))

    if not stale_sources:
        return None

    parts = []
    for name, count in stale_sources:
        if count == -1:
            parts.append(f"{name}: never synced")
        else:
            parts.append(f"{name}: changes detected")

    return f"Armada: {len(stale_sources)} upstream(s) have updates ({', '.join(parts)}). Run /armada sync to review."


def main() -> None:
    notification = check_staleness()
    if notification:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": notification,
            }
        }
        json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
