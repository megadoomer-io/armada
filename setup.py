#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "pyyaml",
# ]
# ///
"""Armada onboarding setup — create config and XDG directories.

Run directly: ./setup.py
Or via uv:    uv run setup.py

Idempotent: safe to re-run after upgrades. On re-run it:
- Creates any new XDG subdirectories added in newer versions
- Ensures the armada upstream exists in config (for self-upgrading)
- Reports what was already in place vs what was added
- Never overwrites existing config without explicit confirmation
"""

import os
import pathlib
import sys

import yaml

SETUP_VERSION = "0.1.0"


def resolve_dir(env_var: str, xdg_var: str, xdg_default: str, subdir: str) -> pathlib.Path:
    if env := os.environ.get(env_var):
        return pathlib.Path(env)
    xdg = os.environ.get(xdg_var, xdg_default)
    return pathlib.Path(xdg).expanduser() / subdir


def config_dir() -> pathlib.Path:
    return resolve_dir("ARMADA_CONFIG_DIR", "XDG_CONFIG_HOME", "~/.config", "armada")


def state_dir() -> pathlib.Path:
    return resolve_dir("ARMADA_STATE_DIR", "XDG_STATE_HOME", "~/.local/state", "armada")


def cache_dir() -> pathlib.Path:
    return resolve_dir("ARMADA_CACHE_DIR", "XDG_CACHE_HOME", "~/.cache", "armada")


def prompt(question: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer or default


def confirm(question: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    answer = input(f"{question}{suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def collect_sources(kind: str) -> list[dict[str, str | list[str]]]:
    sources: list[dict[str, str | list[str]]] = []
    while True:
        if not confirm(f"\nAdd {'an' if not sources else 'another'} {kind}?", default=not sources):
            break
        name = prompt("  Short name (e.g., james, cerebral)")
        repo = prompt("  GitHub repo (e.g., org/repo)")
        paths_raw = prompt("  Path filter (comma-separated, blank for all)", "")
        paths = [p.strip() for p in paths_raw.split(",") if p.strip()] if paths_raw else []
        source: dict[str, str | list[str]] = {"name": name, "repo": repo}
        if paths:
            source["paths"] = paths
        sources.append(source)
    return sources


ARMADA_UPSTREAM = {
    "name": "armada",
    "repo": "megadoomer-io/armada",
    "paths": ["skills/", "knowledge/"],
}


def ensure_armada_upstream(config: dict[str, object]) -> bool:
    """Ensure megadoomer-io/armada is in the upstreams list. Returns True if added."""
    upstreams = config.get("upstreams", [])
    if any(u.get("repo") == "megadoomer-io/armada" for u in upstreams):
        return False
    upstreams.append(ARMADA_UPSTREAM)
    config["upstreams"] = upstreams
    return True


def create_directories() -> tuple[dict[str, pathlib.Path], list[pathlib.Path]]:
    """Create XDG directories. Returns (dirs, newly_created)."""
    dirs = {
        "config": config_dir(),
        "state": state_dir(),
        "cache": cache_dir(),
    }
    required = [
        dirs["config"],
        dirs["state"] / "grains",
        dirs["state"] / "queues",
        dirs["cache"] / "repos",
        dirs["cache"] / "comparisons",
    ]
    created = []
    for d in required:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)
    return dirs, created


def build_config() -> dict[str, object]:
    print("\n" + "=" * 50)
    print("  Armada Setup — Join the Knowledge Network")
    print("=" * 50)

    print("\n--- Identity ---")
    name = prompt("Your GitHub username")
    repo = prompt("Your agent instructions repo (org/repo)")
    agent_root = prompt("Local agent instructions path", "~/.agents/")

    print("\n--- Upstreams (sources you pull knowledge from) ---")
    upstreams = collect_sources("upstream")

    print("\n--- Peers (bidirectional knowledge exchange) ---")
    peers = collect_sources("peer")

    print("\n--- Downstreams (convergence targets, optional) ---")
    downstreams: list[dict[str, object]] = []
    if confirm("Add downstream targets?", default=False):
        for source in collect_sources("downstream"):
            threshold = prompt("  Convergence threshold", "2")
            source["convergence_threshold"] = int(threshold)
            downstreams.append(source)

    config: dict[str, object] = {
        "version": 1,
        "identity": {
            "name": name,
            "repo": repo,
            "agent_root": agent_root,
        },
        "upstreams": upstreams,
        "peers": peers,
        "downstreams": downstreams,
        "settings": {
            "max_open_proposals": 3,
            "sync_check_on_session_start": True,
            "proposal_batch_size": 2,
            "auto_fetch_interval": "daily",
        },
        "preferences": {
            "github_client": "mcp",
        },
    }

    if ensure_armada_upstream(config):
        print("\n  (Auto-added megadoomer-io/armada as upstream for skill updates)")

    return config


def write_config(config: dict[str, object], path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))


def run_fresh_setup() -> None:
    """First-time setup: full interactive config creation."""
    config = build_config()
    directories, _ = create_directories()
    cfg_path = config_dir() / "config.yaml"
    write_config(config, cfg_path)

    print("\n" + "=" * 50)
    print("  Setup Complete")
    print("=" * 50)
    print(f"\n  Config:  {cfg_path}")
    print(f"  State:   {directories['state']}")
    print(f"  Cache:   {directories['cache']}")
    print(f"\n  Upstreams: {len(config.get('upstreams', []))}")
    print(f"  Peers:     {len(config.get('peers', []))}")
    print(f"  Downstreams: {len(config.get('downstreams', []))}")
    print("\n  Next steps:")
    print("    1. Run /armada sync to pull knowledge from your upstreams")
    print("    2. Run /armada propose to share knowledge with your peers")
    print("    3. Run /armada review to check for incoming proposals")
    print()


def run_upgrade_check() -> None:
    """Re-run on existing install: ensure directories, check config, report status."""
    cfg_path = config_dir() / "config.yaml"
    config = yaml.safe_load(cfg_path.read_text())

    print(f"\nArmada setup v{SETUP_VERSION} — checking existing installation")
    print("=" * 50)

    # Ensure directories
    _, created = create_directories()
    if created:
        print(f"\n  Created {len(created)} new directories:")
        for d in created:
            print(f"    + {d}")
    else:
        print("\n  Directories: all present")

    # Ensure armada upstream
    if ensure_armada_upstream(config):
        write_config(config, cfg_path)
        print("  Config: added megadoomer-io/armada upstream (for self-upgrading)")
    else:
        print("  Config: armada upstream present")

    # Report current state
    upstreams = config.get("upstreams", [])
    peers = config.get("peers", [])
    print(f"\n  Identity: {config.get('identity', {}).get('name', 'unknown')}")
    print(f"  Upstreams: {len(upstreams)}")
    print(f"  Peers: {len(peers)}")

    # Check for grain state files
    grains_dir = state_dir() / "grains"
    grain_files = list(grains_dir.glob("*.yaml")) if grains_dir.exists() else []
    queues_dir = state_dir() / "queues"
    queue_files = list(queues_dir.glob("*.yaml")) if queues_dir.exists() else []
    print(f"  Grain state files: {len(grain_files)}")
    print(f"  Proposal queues: {len(queue_files)}")

    if not created and not ensure_armada_upstream(config):
        print("\n  Everything up to date. No changes needed.")
    print()


def main() -> None:
    cfg_path = config_dir() / "config.yaml"

    if cfg_path.exists():
        if "--force" in sys.argv:
            run_fresh_setup()
        elif "--check" in sys.argv or len(sys.argv) == 1:
            run_upgrade_check()
        else:
            print(f"\nArmada config exists at {cfg_path}")
            print("  Re-running setup to check for updates...")
            run_upgrade_check()
            if confirm("\nRecreate config from scratch?", default=False):
                run_fresh_setup()
    else:
        run_fresh_setup()


if __name__ == "__main__":
    main()
