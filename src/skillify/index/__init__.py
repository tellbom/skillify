"""Postgres index of published skills (T2.2) — one row per (namespace, name, version),
populated by the publish pipeline (T1.3 CLI publish / T2.1 webhook), read by the future
Web backend (T3.1). Tests run this against SQLite; production points at real Postgres.
"""
