# Deterministic File Processing

Two standard-library processors cover text word frequency and grouped CSV summaries. Each
run creates a new output directory plus `changes.json`; source files are never overwritten.
The pinned implementation has no network dependencies (`requirements.lock`).
