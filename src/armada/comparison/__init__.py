"""Comparison strategies for Armada sync — full-repo and chunked."""

from armada.comparison.chunked import ComparisonChunk, chunk_changes
from armada.comparison.prompts import build_chunk_prompt, build_onboarding_prompt

__all__ = [
    "ComparisonChunk",
    "build_chunk_prompt",
    "build_onboarding_prompt",
    "chunk_changes",
]
