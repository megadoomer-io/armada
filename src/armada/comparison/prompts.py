"""Prompt templates for LLM comparison — onboarding and incremental."""

import armada.comparison.chunked as chunked_mod

_ONBOARDING_INSTRUCTIONS = (
    "For each piece of knowledge in the source that the local set"
    " doesn't have, or where the source has a meaningfully"
    " different approach:\n"
    "\n"
    '1. Assign a semantic_id (lowercase-kebab-case, e.g.,'
    ' "kustomize-patch-strategy")\n'
    "2. Write a 1-2 sentence description of what the knowledge"
    " covers\n"
    "3. Classify as: new (source has it, local doesn't),"
    " different (both have it, different approach),"
    " or equivalent (same knowledge, different structure)\n"
    '4. For "new" and "different" items, explain what the local'
    " set would gain\n"
    "\n"
    "Focus on actionable knowledge. Skip structural differences"
    " (file naming, directory layout) and tool-specific"
    " configuration (IDE settings, shell aliases) unless they"
    " encode a reusable pattern.\n"
    "\n"
    "Output as a structured list with semantic_id, description,"
    " classification, and value_summary for each grain."
)

_CHUNK_INSTRUCTIONS = (
    "For each file:\n"
    "1. Assign a semantic_id (lowercase-kebab-case)\n"
    "2. Summarize what knowledge it contains (1-2 sentences)\n"
    "3. Is this significant enough to surface for review?"
    " (yes/no with reason)\n"
    "4. If you have related local instructions, what's the"
    " delta?\n"
    "\n"
    "Only surface changes that add meaningful knowledge or"
    " represent a different approach worth considering."
    " Skip minor wording changes, formatting, and structural"
    " reorganization."
)


def build_onboarding_prompt(
    source_name: str,
    source_contents: dict[str, str],
    local_contents: dict[str, str],
) -> str:
    """Build the full-repo comparison prompt for onboarding (first sync).

    This is the expensive path: both complete instruction sets in one prompt.
    Recommended model: Opus for accurate semantic grain identification.
    """
    source_section = _format_file_set("Source", source_name, source_contents)
    local_section = _format_file_set("Local", "your instructions", local_contents)

    return (
        "Compare these two agent instruction sets and identify"
        " knowledge gaps.\n\n"
        f"{source_section}\n\n"
        f"{local_section}\n\n"
        f"{_ONBOARDING_INSTRUCTIONS}"
    )


def build_chunk_prompt(chunk: chunked_mod.ComparisonChunk) -> str:
    """Build a per-chunk comparison prompt for incremental sync.

    Smaller and cheaper than onboarding: only the changed files,
    with local equivalents for context.
    """
    source_files = "\n\n".join(
        f"### {path}\n```\n{content}\n```"
        for path, content in chunk.source_contents.items()
    )

    local_files = ""
    has_local = any(v is not None for v in chunk.local_contents.values())
    if has_local:
        local_parts = []
        for path, content in chunk.local_contents.items():
            if content is not None:
                local_parts.append(f"### {path}\n```\n{content}\n```")
        if local_parts:
            local_files = (
                "\n\n## Your related instructions\n\n"
                + "\n\n".join(local_parts)
            )

    change_type = "new files" if chunk.is_new_file_only else "changed files"

    return (
        f"Review these {change_type} from"
        f" {chunk.source_name}'s agent instructions.\n\n"
        f"## Source changes\n\n{source_files}"
        f"{local_files}\n\n"
        f"{_CHUNK_INSTRUCTIONS}"
    )


def _format_file_set(label: str, name: str, contents: dict[str, str]) -> str:
    """Format a set of files for inclusion in a prompt."""
    if not contents:
        return f"## {label} ({name})\n\nNo files."

    parts = [f"## {label} ({name})\n"]
    for path, content in sorted(contents.items()):
        parts.append(f"### {path}\n```\n{content}\n```")
    return "\n\n".join(parts)
