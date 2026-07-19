"""Thin integration for the pinned external multi-agent-shogun runtime."""

from skillify.agent.shogun.distribution import (
    SHOGUN_COMMIT, SHOGUN_VERSION, ShogunDistributionError,
    check_host_dependencies, load_manifest, verify_artifact,
)

__all__ = [
    "SHOGUN_COMMIT", "SHOGUN_VERSION", "ShogunDistributionError",
    "check_host_dependencies", "load_manifest", "verify_artifact",
]
