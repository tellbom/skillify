"""FastAPI app exposing the Forgejo webhook endpoint (T2.1c).

Run standalone with `skillify-webhook` (console script -> `run()`) or
`uvicorn skillify.webhook.app:app`. Configure via the same `~/.skillify/config.yaml` /
`SKILLIFY_*` env vars as `skillctl` (needs `forgejo_url`/`forgejo_token`; `webhook_secret`
is optional but strongly recommended in production — without it, this endpoint accepts any
POST unauthenticated. See PLAN.md §6.4 "agent 自拉取安全边界" for the broader intranet+token
posture this follows.
"""

from __future__ import annotations

import json

from fastapi import FastAPI, Header, HTTPException, Request

from skillify.common.config import load_config
from skillify.webhook.handler import WebhookHandlingError, handle_push_event
from skillify.webhook.verify import verify_forgejo_signature

app = FastAPI(title="skillify-webhook", description="Forgejo push/tag -> package -> Release (T2.1)")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhook/forgejo")
async def forgejo_webhook(
    request: Request,
    x_forgejo_signature: str | None = Header(default=None),
    x_gitea_signature: str | None = Header(default=None),
    x_forgejo_event: str | None = Header(default=None),
    x_gitea_event: str | None = Header(default=None),
) -> dict[str, object]:
    cfg = load_config()
    body = await request.body()

    if cfg.webhook_secret:
        signature = x_forgejo_signature or x_gitea_signature
        if not verify_forgejo_signature(body, signature, cfg.webhook_secret):
            raise HTTPException(status_code=401, detail="invalid webhook signature")

    event = x_forgejo_event or x_gitea_event or "push"
    if event != "push":
        return {"status": "ignored", "detail": f"unhandled event type {event!r}"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON payload: {exc}") from exc

    try:
        result = handle_push_event(payload, cfg)
    except WebhookHandlingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "status": result.status,
        "detail": result.detail,
        "org": result.org,
        "repo": result.repo,
        "tag": result.tag,
        "releaseUrl": result.release_html_url,
        "indexError": result.index_error,
    }


def run() -> None:
    """Entry point for the `skillify-webhook` console script."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8088)


if __name__ == "__main__":
    run()
