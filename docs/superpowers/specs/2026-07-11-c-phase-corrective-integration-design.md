# C Phase Corrective Integration Design

## Scope

This correction is limited to three accepted review findings:

1. Replay the 13 C-phase commits onto the reviewed `39e03e1` M-DM+A+B+C-3 baseline.
2. Prevent a comment from being deleted through a route for a different skill.
3. Prevent one user's publish attempt from overwriting another user's publish-job row.

Frontend RBAC expansion and unrelated TypeScript cleanup remain out of scope.

## Baseline Integration

Create a local backup branch at the current C-phase tip, then rebase `main` from
`origin/main` onto `39e03e1`. Resolve conflicts by preserving the reviewed baseline's
deployment and ownership boundaries while layering C-phase behavior on top:

- Skillify business data uses the external DM8 schema.
- Forgejo PostgreSQL remains Forgejo-owned.
- `init_db()` creates tables only for SQLite tests.
- C-3 continues to commit validated Web-upload source and version tags to Forgejo Git.
- The complete backend/frontend Docker and Nginx topology remains present.

## Comment Ownership

`soft_delete_comment` will consume `namespace` and `name` in addition to `comment_id`.
The row lookup must match all three values. A mismatched route returns the existing
not-found behavior, so no information about another skill's comment is exposed and no row
is changed.

## Publish-Job Ownership

The publish-job identity becomes `(namespace, name, version, initiator)` in both SQLAlchemy
and `infra/dm8-init/03-c2-my-skills.sql`. A retry by the same user updates that user's row;
an attempt by a different user creates or updates a separate row.

Because the project has no production history, the incremental SQL remains a clean-build
fact source and does not include compatibility migration logic for an older constraint.

## Verification

Use test-first regression coverage for both data-ownership defects. Then run the complete
Python test suite, frontend tests, Vue type checking, production build, OpenAPI generation,
`git diff --check`, and checks proving `main` contains `39e03e1` and the required DM8/C-3
deployment files.
