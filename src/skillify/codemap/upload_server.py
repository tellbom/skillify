"""P1-3: temporary, low-coupled upload-verification entry point.

Standalone FastAPI app — deliberately NOT wired into the production
`skillify.web.app` — used only to validate the endpoint->server upload
mechanics for Phase 1. Auth is a single bearer token; real Keycloak/HMAC
dual-auth lands in P2-3 per the plan's task list.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Header, HTTPException, UploadFile

from skillify.codemap.upload_verify import UploadVerifyError, safe_extract, validate_task_id, verify_checksum


def build_app(*, tasks_root: Path, token: str, max_upload_bytes: int) -> FastAPI:
    tasks_root = Path(tasks_root)
    app = FastAPI(title="codemap-upload-verify (P1-3, temporary)")

    @app.post("/codemap/upload")
    async def upload(
        task_id: str = Form(...),
        sha256: str = Form(...),
        tar: UploadFile = ...,
        authorization: str | None = Header(default=None),
    ) -> dict:
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="unauthorized")

        try:
            safe_task_id = validate_task_id(task_id)
        except UploadVerifyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        task_dir = tasks_root / safe_task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        tmp_tar = task_dir / "upload.tar.gz"

        size = 0
        with open(tmp_tar, "wb") as fh:
            while chunk := await tar.read(1024 * 1024):
                size += len(chunk)
                if size > max_upload_bytes:
                    fh.close()
                    tmp_tar.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="upload too large")
                fh.write(chunk)

        try:
            verify_checksum(tmp_tar, sha256)
            members = safe_extract(tmp_tar, task_dir / "source")
        except UploadVerifyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        finally:
            tmp_tar.unlink(missing_ok=True)

        return {"task_id": safe_task_id, "extracted_files": len(members)}

    return app


def run() -> None:
    """Launch the temporary upload-verification server (`python -m skillify.codemap.upload_server`)."""
    import os

    import uvicorn

    app = build_app(
        tasks_root=Path(os.environ.get("SKILLIFY_CODEMAP_TASKS_ROOT", "/srv/codemap/tasks")),
        token=os.environ["SKILLIFY_CODEMAP_UPLOAD_TOKEN"],
        max_upload_bytes=int(os.environ.get("SKILLIFY_CODEMAP_MAX_UPLOAD_BYTES", 200 * 1024 * 1024)),
    )
    uvicorn.run(
        app,
        host=os.environ.get("SKILLIFY_CODEMAP_UPLOAD_HOST", "127.0.0.1"),
        port=int(os.environ.get("SKILLIFY_CODEMAP_UPLOAD_PORT", "8098")),
    )


if __name__ == "__main__":
    run()
