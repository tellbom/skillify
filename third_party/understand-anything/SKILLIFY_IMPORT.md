# Skillify import record

This directory is a complete source import of Understand Anything.

- Upstream repository: `Egonex-AI/Understand-Anything`
- Upstream base commit: `2cda14e`
- Skillify portal integration commit: `0e336c8`
- License: MIT; see `LICENSE`

Skillify-specific runtime entrypoint:
`../../scripts/understand-anything-portal.sh`

The imported service remains process-, container-, and storage-isolated from
Skillify's existing code-map implementation.
