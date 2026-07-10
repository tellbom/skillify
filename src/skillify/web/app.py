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
from skillify.index.comments import add_comment, list_comments
from skillify.index.db import init_db, make_engine
from skillify.index.events import record_event
from skillify.index.ownership import NamespaceOwnershipError
from skillify.index.queries import get_versions, leaderboard as leaderboard_query
from skillify.index.ratings import rating_stats, upsert_rating
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
    RatingIn,
    RatingOut,
    SkillDetail,
    SkillSummary,
    UploadResponse,
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
def skill_detail(namespace: str, name: str, _claims: dict = Depends(require_keycloak_user)) -> SkillDetail:
    cfg = load_config()
    session = _session()
    try:
        detail = service.get_skill_detail(session, cfg, namespace, name)
    finally:
        session.close()
    if detail is None:
        raise HTTPException(status_code=404, detail=f"{namespace}/{name} not found in index")
    return detail


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


@app.get("/api/skills/{namespace}/{name}/comments", response_model=list[CommentOut])
def get_comments(namespace: str, name: str, _claims: dict = Depends(require_keycloak_user)) -> list[CommentOut]:
    """M-A (docs/review-m2-m6.md): market-wide login requirement — reads require a valid
    Keycloak session too, not just writes. Superseded the earlier T5.1 "public read" design."""
    session = _session()
    try:
        comments = list_comments(session, namespace, name)
        return [
            CommentOut(id=c.id, namespace=c.namespace, name=c.name, author=c.author, body=c.body, createdAt=c.created_at)
            for c in comments
        ]
    finally:
        session.close()


@app.post("/api/skills/{namespace}/{name}/comments", response_model=CommentOut)
def post_comment(
    namespace: str, name: str, payload: CommentIn, claims: dict = Depends(require_keycloak_user)
) -> CommentOut:
    """T5.1: posting requires a valid Keycloak session (M4a), same as upload."""
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="comment body must not be empty")
    if len(body) > 4000:
        raise HTTPException(status_code=400, detail="comment body too long (max 4000 chars)")

    author = claims.get("preferred_username") or claims.get("sub") or "unknown"
    session = _session()
    try:
        comment = add_comment(
            session, namespace=namespace, name=name, author=author, body=body,
            created_at=datetime.now(timezone.utc),
        )
        session.commit()
        return CommentOut(
            id=comment.id, namespace=comment.namespace, name=comment.name,
            author=comment.author, body=comment.body, createdAt=comment.created_at,
        )
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


def run() -> None:
    """Entry point for the `skillify-web` console script."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8089)


if __name__ == "__main__":
    run()
