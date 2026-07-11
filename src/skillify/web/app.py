"""FastAPI app for the community site backend (T3.1).

Run with `skillify-web` (console script) or `uvicorn skillify.web.app:app`. Needs
`index_db_url` configured (T2.2) to serve anything; `forgejo_url`/`forgejo_token` are
optional but without them skill detail responses won't have README/SKILL.md/download URLs.
"""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker

from skillify.common.config import load_config
from skillify.index.comments import (
    CommentNotFoundError,
    CommentPermissionError,
    add_comment,
    list_comments_for_display,
    soft_delete_comment,
)
from skillify.index.db import init_db, make_engine
from skillify.index.events import record_event
from skillify.index.my_skills import list_my_namespaces, list_my_skills, my_usage_stats
from skillify.index.ownership import NamespaceOwnershipError
from skillify.index.publish_jobs import list_my_failed_jobs, list_my_jobs
from skillify.index.queries import get_versions, leaderboard as leaderboard_query, list_latest
from skillify.index.ratings import rating_stats, upsert_rating
from skillify.index.star import add_star, remove_star, star_counts
from skillify.index.subscriptions import add_subscription, list_subscriptions_for_user, remove_subscription
from skillify.index.yank import VersionNotFoundError, can_manage_version, set_yanked
from skillify.packaging.pack import PackagingError
from skillify.publish.forgejo_client import ForgejoError
from skillify.publish.publisher import AlreadyPublishedError, PublishNotConfiguredError
from skillify.web import service
from skillify.web.auth import require_keycloak_user
from skillify.web.schemas import (
    CommentIn,
    CommentOut,
    EventIn,
    InstallInfo,
    LeaderboardEntry,
    MyNamespaceOut,
    MySubscriptionOut,
    MyUsageStats,
    PublishJobOut,
    RatingIn,
    RatingOut,
    SkillDetail,
    SkillSummary,
    StarOut,
    SubscriptionOut,
    UploadResponse,
    VersionDiff,
    VersionInfo,
    YankOut,
)
from skillify.web.upload import UnsafeUpload
from skillify.web.upload_service import NamespaceOwnershipNotConfiguredError, UploadRejected, handle_upload

app = FastAPI(title="skillify-web", description="Community site backend (T3.1)")

# Dev-friendly default; an intranet deployment should restrict this to the actual frontend
# origin(s) via SKILLIFY_WEB_CORS_ORIGINS (comma-separated) — see run().
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"]
)


def _session() -> Session:
    cfg = load_config()
    if not cfg.index_db_url:
        raise HTTPException(status_code=503, detail="index_db_url not configured on this service")
    engine = make_engine(cfg.index_db_url)
    init_db(engine)
    return sessionmaker(bind=engine, future=True)()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/skills", response_model=list[SkillSummary])
def list_skills(
    q: str | None = Query(default=None, description="Search query (name/description)"),
    _claims: dict = Depends(require_keycloak_user),
) -> list[SkillSummary]:
    session = _session()
    try:
        return service.list_skills(session, q)
    finally:
        session.close()


@app.get("/api/search", response_model=list[SkillSummary])
def search_skills(
    q: str = Query(..., description="Search query (name/description)"),
    _claims: dict = Depends(require_keycloak_user),
) -> list[SkillSummary]:
    session = _session()
    try:
        return service.list_skills(session, q)
    finally:
        session.close()


@app.get("/api/skills/{namespace}/{name}", response_model=SkillDetail)
def skill_detail(
    namespace: str,
    name: str,
    version: str | None = Query(default=None, description="Explicit version (bypasses yanked exclusion)"),
    claims: dict = Depends(require_keycloak_user),
) -> SkillDetail:
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    cfg = load_config()
    session = _session()
    try:
        detail = service.get_skill_detail(session, cfg, namespace, name, version=version, username=username)
    finally:
        session.close()
    if detail is None:
        raise HTTPException(status_code=404, detail=f"{namespace}/{name} not found in index")
    return detail


@app.get("/api/skills/{namespace}/{name}/versions", response_model=list[VersionInfo])
def skill_versions(namespace: str, name: str, _claims: dict = Depends(require_keycloak_user)) -> list[VersionInfo]:
    """C-1 — the full version timeline (yanked and not), release notes best-effort from
    Forgejo. Unlike `skill_detail`, this deliberately does not filter yanked versions out —
    the whole point is to show yank status per version."""
    cfg = load_config()
    session = _session()
    try:
        versions = service.list_versions(session, cfg, namespace, name)
    finally:
        session.close()
    if not versions:
        raise HTTPException(status_code=404, detail=f"{namespace}/{name} not found in index")
    return versions


@app.get("/api/skills/{namespace}/{name}/diff", response_model=VersionDiff)
def skill_diff(
    namespace: str,
    name: str,
    from_: str = Query(..., alias="from"),
    to: str = Query(...),
    _claims: dict = Depends(require_keycloak_user),
) -> VersionDiff:
    """C-1 — pure computation (nothing persisted): file-tree diff between two versions via
    Forgejo's recursive git tree API. 404 if either version isn't in the index; 400 if
    Forgejo isn't configured (can't compute a tree diff without it)."""
    cfg = load_config()
    if not cfg.forgejo_url or not cfg.forgejo_token:
        raise HTTPException(status_code=400, detail="forgejo_url/forgejo_token not configured")
    session = _session()
    try:
        versions = {v.version for v in get_versions(session, namespace, name)}
    finally:
        session.close()
    if from_ not in versions:
        raise HTTPException(status_code=404, detail=f"{namespace}/{name}@{from_} not found in index")
    if to not in versions:
        raise HTTPException(status_code=404, detail=f"{namespace}/{name}@{to} not found in index")
    try:
        return service.diff_versions(cfg, namespace, name, from_, to)
    except ForgejoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _authorize_version_management(session: Session, *, namespace: str, name: str, version: str, username: str) -> None:
    """Author or namespace owner may yank/unyank — shared by both endpoints below."""
    entries = get_versions(session, namespace, name)
    entry = next((e for e in entries if e.version == version), None)
    if entry is None:
        raise VersionNotFoundError(namespace, name, version)
    if entry.author == username:
        return
    if can_manage_version(session, namespace=namespace, username=username):
        return
    raise HTTPException(status_code=403, detail="only the author or namespace owner may yank/unyank this version")


@app.post("/api/skills/{namespace}/{name}/versions/{version}/yank", response_model=YankOut)
def yank_version(
    namespace: str, name: str, version: str, claims: dict = Depends(require_keycloak_user)
) -> YankOut:
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        _authorize_version_management(session, namespace=namespace, name=name, version=version, username=username)
        entry = set_yanked(session, namespace=namespace, name=name, version=version, yanked=True)
        return YankOut(version=entry.version, yanked=entry.yanked)
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        session.close()


@app.post("/api/skills/{namespace}/{name}/versions/{version}/unyank", response_model=YankOut)
def unyank_version(
    namespace: str, name: str, version: str, claims: dict = Depends(require_keycloak_user)
) -> YankOut:
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        _authorize_version_management(session, namespace=namespace, name=name, version=version, username=username)
        entry = set_yanked(session, namespace=namespace, name=name, version=version, yanked=False)
        return YankOut(version=entry.version, yanked=entry.yanked)
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        session.close()


@app.get("/api/skills/{namespace}/{name}/install", response_model=InstallInfo)
def skill_install_info(namespace: str, name: str, _claims: dict = Depends(require_keycloak_user)) -> InstallInfo:
    cfg = load_config()
    return InstallInfo(
        installCommand=service.install_command(namespace, name),
        agentPrompt=service.agent_prompt(namespace, name, cfg),
    )


@app.get("/api/skills/{namespace}/{name}/orchestration")
def skill_orchestration(namespace: str, name: str, _claims: dict = Depends(require_keycloak_user)) -> dict:
    """T6.3 — reserved hook: exposes skill.yaml's `orchestration` field (spec §3, free-form)
    for a future orchestrator to read. No orchestration engine is implemented; this just
    makes the already-validated field queryable without re-fetching the artifact from
    Forgejo. Returns the latest published version's `orchestration` object (`{}` if the
    skill never declared one)."""
    session = _session()
    try:
        versions = get_versions(session, namespace, name)
    finally:
        session.close()
    if not versions:
        raise HTTPException(status_code=404, detail=f"{namespace}/{name} not found in index")
    return versions[0].orchestration or {}


@app.post("/api/skills/{namespace}/{name}/star", response_model=StarOut)
def star_skill(namespace: str, name: str, claims: dict = Depends(require_keycloak_user)) -> StarOut:
    """C-5 — idempotent: starring an already-starred skill just returns the current state."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        add_star(session, namespace=namespace, name=name, author=username, created_at=datetime.now(timezone.utc))
        count = star_counts(session).get((namespace, name), 0)
        return StarOut(starred=True, starCount=count)
    finally:
        session.close()


@app.delete("/api/skills/{namespace}/{name}/star", response_model=StarOut)
def unstar_skill(namespace: str, name: str, claims: dict = Depends(require_keycloak_user)) -> StarOut:
    """C-5 — no-op (not an error) if the skill wasn't starred by this user."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        remove_star(session, namespace=namespace, name=name, author=username)
        count = star_counts(session).get((namespace, name), 0)
        return StarOut(starred=False, starCount=count)
    finally:
        session.close()


@app.post("/api/skills/{namespace}/{name}/subscription", response_model=SubscriptionOut)
def subscribe_skill(namespace: str, name: str, claims: dict = Depends(require_keycloak_user)) -> SubscriptionOut:
    """C-5 — idempotent subscribe. No notification tracking (explicitly deferred, see
    `subscriptions.py` docstring) — this only records the intent to be subscribed;
    `GET /api/my/subscriptions` is a snapshot query, not a feed."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        add_subscription(session, namespace=namespace, name=name, author=username, created_at=datetime.now(timezone.utc))
        return SubscriptionOut(subscribed=True)
    finally:
        session.close()


@app.delete("/api/skills/{namespace}/{name}/subscription", response_model=SubscriptionOut)
def unsubscribe_skill(namespace: str, name: str, claims: dict = Depends(require_keycloak_user)) -> SubscriptionOut:
    """C-5 — no-op (not an error) if the skill wasn't subscribed to by this user."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        remove_subscription(session, namespace=namespace, name=name, author=username)
        return SubscriptionOut(subscribed=False)
    finally:
        session.close()


@app.get("/api/skills/{namespace}/{name}/comments", response_model=list[CommentOut])
def get_comments(namespace: str, name: str, _claims: dict = Depends(require_keycloak_user)) -> list[CommentOut]:
    """M-A (docs/review-m2-m6.md): market-wide login requirement — reads require a valid
    Keycloak session too, not just writes. Superseded the earlier T5.1 "public read" design.

    C-5: uses `list_comments_for_display` so soft-deleted comments come back with their body
    replaced by a placeholder rather than the original text, while keeping `id`/`parentId` so
    the frontend can still render the reply tree."""
    session = _session()
    try:
        comments = list_comments_for_display(session, namespace, name)
        return [
            CommentOut(
                id=c.id, namespace=c.namespace, name=c.name, author=c.author, body=c.body,
                createdAt=c.created_at, parentId=c.parent_id, deleted=c.deleted,
            )
            for c in comments
        ]
    finally:
        session.close()


@app.post("/api/skills/{namespace}/{name}/comments", response_model=CommentOut)
def post_comment(
    namespace: str, name: str, payload: CommentIn, claims: dict = Depends(require_keycloak_user)
) -> CommentOut:
    """T5.1: posting requires a valid Keycloak session (M4a), same as upload. C-5: optional
    `parentId` makes this a reply; `add_comment` validates the parent belongs to the same
    (namespace, name) and raises `ValueError` (mapped to 400) otherwise."""
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="comment body must not be empty")
    if len(body) > 4000:
        raise HTTPException(status_code=400, detail="comment body too long (max 4000 chars)")

    author = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        try:
            comment = add_comment(
                session, namespace=namespace, name=name, author=author, body=body,
                created_at=datetime.now(timezone.utc), parent_id=payload.parentId,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session.commit()
        return CommentOut(
            id=comment.id, namespace=comment.namespace, name=comment.name,
            author=comment.author, body=comment.body, createdAt=comment.created_at,
            parentId=comment.parent_id, deleted=comment.deleted,
        )
    finally:
        session.close()


@app.delete("/api/skills/{namespace}/{name}/comments/{comment_id}", status_code=204)
def delete_comment(
    namespace: str, name: str, comment_id: int, claims: dict = Depends(require_keycloak_user)
) -> None:
    """C-5: soft-delete. Only the comment's own author or the skill's namespace owner may
    delete it — the "author" half compares `comment.author` directly (a comment's author is
    not necessarily the skill's author), the "namespace owner" half reuses
    `yank.py::can_manage_version`'s namespace-owner check (same query, no need to duplicate
    it)."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        is_owner = can_manage_version(session, namespace=namespace, username=username)
        try:
            soft_delete_comment(session, comment_id=comment_id, actor_username=username, is_namespace_owner=is_owner)
        except CommentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except CommentPermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    finally:
        session.close()


@app.get("/api/leaderboard", response_model=list[LeaderboardEntry])
def get_leaderboard(
    dimension: str = Query(default="installs", description="installs | rating | recent"),
    _claims: dict = Depends(require_keycloak_user),
) -> list[LeaderboardEntry]:
    session = _session()
    try:
        rows = leaderboard_query(session, dimension)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()
    return [
        LeaderboardEntry(
            namespace=r.entry.namespace, name=r.entry.name, description=r.entry.description,
            installCount=r.install_count, ratingAverage=r.rating_average, ratingCount=r.rating_count,
            publishedAt=r.entry.published_at,
        )
        for r in rows
    ]


@app.post("/api/skills/{namespace}/{name}/rating", response_model=RatingOut)
def rate_skill(
    namespace: str, name: str, payload: RatingIn, claims: dict = Depends(require_keycloak_user)
) -> RatingOut:
    """T5.2: one 1-5 rating per logged-in user per skill; re-rating updates in place."""
    author = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        try:
            rating = upsert_rating(
                session, namespace=namespace, name=name, author=author, score=payload.score,
                created_at=datetime.now(timezone.utc),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session.commit()
        stats = rating_stats(session)
        avg, count = stats.get((namespace, name), (None, 0))
        return RatingOut(namespace=namespace, name=name, ratingAverage=avg, ratingCount=count, yourScore=rating.score)
    finally:
        session.close()


@app.post("/api/skills/{namespace}/{name}/events", status_code=204)
def report_event(namespace: str, name: str, payload: EventIn) -> None:
    """T5.2 (install count) / T6.2 (run report stub) — see TASKS.md T6.2 for the documented
    privacy boundary. Deliberately anonymous/unauthenticated: this fires from `skillctl`
    (no Keycloak session available there — that's a browser concept), not the web frontend,
    and carries no PII beyond an opaque client-generated `machineId`."""
    session = _session()
    try:
        record_event(
            session, namespace=namespace, name=name, version=payload.version,
            event_type=payload.eventType, success=payload.success, machine_id=payload.machineId,
            occurred_at=datetime.now(timezone.utc),
        )
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        session.close()


@app.post("/api/skills/upload", response_model=UploadResponse)
async def upload_skill(
    file: UploadFile = File(...), claims: dict = Depends(require_keycloak_user)
) -> UploadResponse:
    """T4.2: browser upload of a skill package (.zip of a skill dir). Protected by
    Keycloak bearer auth (M4a); publishes under the backend's own Forgejo service-account
    token, attributing the uploader's Keycloak identity in the Release notes (see
    upload_service.handle_upload's docstring / TASKS.md M4 for why this isn't a per-user
    Forgejo token)."""
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="upload must be a .zip of the skill directory")

    cfg = load_config()
    cfg.ensure_dirs()

    # M-D (docs/review-m2-m6.md): stream into the cap instead of `await file.read()`, which
    # buffers the whole body in memory regardless of size — Content-Length can't be trusted
    # alone (missing/spoofed/chunked), so the real bound is enforced while reading.
    work_dir = cfg.cache_dir / "web-upload" / uuid.uuid4().hex
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / "upload.zip"
    total = 0
    with zip_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > cfg.max_upload_bytes:
                out.close()
                shutil.rmtree(work_dir, ignore_errors=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"upload exceeds the {cfg.max_upload_bytes} byte limit",
                )
            out.write(chunk)

    uploader = claims.get("preferred_username") or claims.get("sub") or "unknown"

    try:
        result = handle_upload(zip_path, cfg, uploader=uploader, work_dir=work_dir)
    except UploadRejected as exc:
        raise HTTPException(
            status_code=422,
            detail=[{"path": i.path, "message": i.message} for i in exc.issues],
        ) from exc
    except UnsafeUpload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NamespaceOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NamespaceOwnershipNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PublishNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AlreadyPublishedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PackagingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ForgejoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    pack_result = result.pack_result
    return UploadResponse(
        namespace=pack_result.namespace,
        name=pack_result.name,
        version=pack_result.version,
        releaseUrl=result.release_html_url,
        indexError=result.index_error,
    )


@app.get("/api/my/skills", response_model=list[SkillSummary])
def my_skills(claims: dict = Depends(require_keycloak_user)) -> list[SkillSummary]:
    """C-2 — the "My Skills" workspace: latest (non-yanked) version of every skill authored
    by the caller, same shape as `GET /api/skills` for reuse on the frontend."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        entries = list_my_skills(session, username)
        return [
            SkillSummary(
                namespace=e.namespace, name=e.name, version=e.version, description=e.description,
                author=e.author, tags=e.tags, publishedAt=e.published_at,
            )
            for e in entries
        ]
    finally:
        session.close()


@app.get("/api/my/namespaces", response_model=list[MyNamespaceOut])
def my_namespaces(claims: dict = Depends(require_keycloak_user)) -> list[MyNamespaceOut]:
    """C-2 — namespaces the caller owns (first-publish-wins, see `SkillNamespaceOwner`)."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        owners = list_my_namespaces(session, username)
        return [MyNamespaceOut(namespace=o.namespace, claimedAt=o.claimed_at) for o in owners]
    finally:
        session.close()


@app.get("/api/my/publish-jobs", response_model=list[PublishJobOut])
def my_publish_jobs(
    status: str = Query(default="failed", description="failed | all"),
    claims: dict = Depends(require_keycloak_user),
) -> list[PublishJobOut]:
    """C-2 — visibility into the caller's own web-upload publish attempts, most notably the
    failed ones (`skill_publish_jobs`, written by `upload_service.handle_upload`). There is
    no dedicated retry endpoint: retrying means re-submitting the same zip to
    `POST /api/skills/upload` — Task 3's draft-resume mechanism in `publish_skill_dir` makes
    that safe to redo (it skips assets already uploaded to the stranded draft release
    rather than duplicating them). The web upload path keeps no server-side copy of the
    extracted source after a failure (`work_dir` is always cleaned up), so "re-upload the
    zip" is the only realistic resumption unit here."""
    if status not in ("failed", "all"):
        raise HTTPException(status_code=400, detail="status must be 'failed' or 'all'")
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        jobs = list_my_failed_jobs(session, username) if status == "failed" else list_my_jobs(session, username)
        return [
            PublishJobOut(
                namespace=j.namespace, name=j.name, version=j.version, status=j.status,
                errorMessage=j.error_message, createdAt=j.created_at, updatedAt=j.updated_at,
            )
            for j in jobs
        ]
    finally:
        session.close()


@app.get("/api/my/usage", response_model=MyUsageStats)
def my_usage(claims: dict = Depends(require_keycloak_user)) -> MyUsageStats:
    """C-2 — summary stats (total skills authored, total installs across them) for the "My
    Skills" page header. Not in the brief's three-endpoint list verbatim, but
    `my_usage_stats` was required as index-layer aggregation for that page — exposed here
    rather than left unreachable."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        stats = my_usage_stats(session, username)
        return MyUsageStats(**stats)
    finally:
        session.close()


@app.get("/api/my/subscriptions", response_model=list[MySubscriptionOut])
def my_subscriptions(claims: dict = Depends(require_keycloak_user)) -> list[MySubscriptionOut]:
    """C-5 — snapshot of "what is currently the latest version of everything I'm subscribed
    to." Deliberately not a feed/inbox (no read/unread tracking — a dedicated notifications
    table is explicitly deferred, see `subscriptions.py`): each call just re-resolves the
    current latest (non-yanked) version for every subscribed (namespace, name) pair. A
    subscription whose skill has since been entirely yanked (so it no longer appears in
    `list_latest`) is silently omitted rather than erroring — there is no "latest version" to
    report for it."""
    username = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        subscribed = set(list_subscriptions_for_user(session, username))
        if not subscribed:
            return []
        latest_by_skill = {(e.namespace, e.name): e for e in list_latest(session)}
        return [
            MySubscriptionOut(
                namespace=ns, name=n, latestVersion=entry.version, publishedAt=entry.published_at
            )
            for (ns, n) in subscribed
            if (entry := latest_by_skill.get((ns, n))) is not None
        ]
    finally:
        session.close()


def run() -> None:
    """Entry point for the `skillify-web` console script."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8089)


if __name__ == "__main__":
    run()
