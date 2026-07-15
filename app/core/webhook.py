"""FastAPI webhook receiver.

Verifies GitHub's HMAC-SHA256 webhook signature before trusting any payload
(without this, anyone who guesses your endpoint URL could trigger fake PR
reviews or spam your GitHub App's rate limit). Only `pull_request` events
with action `opened` or `synchronize` (new commits pushed) trigger a review;
everything else is acknowledged and ignored.

The actual review runs in a FastAPI BackgroundTask so we can return 200 to
GitHub immediately — GitHub retries webhooks that don't get a fast response,
and a full multi-agent review can take well over GitHub's ~10s timeout.
"""
import hashlib
import hmac

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from app.agents.supervisor import run_review
from app.core.config import settings
from app.core.logging_setup import configure_logging, get_logger
from app.rag.standards_store import standards_store
import sys
import asyncio

configure_logging()
logger = get_logger(__name__)

app = FastAPI(title="CodeGuardian AI", version="0.1.0")

logger.info("startup_config", groq_model=settings.groq_model)

_TRIGGER_ACTIONS = {"opened", "synchronize", "reopened"}


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

@app.on_event("startup")
async def startup() -> None:
    # Index the standards doc once at boot; idempotent, cheap no-op on restarts.
    standards_store.index_standards_doc()
    logger.info("startup_complete")


def _verify_signature(payload_body: bytes, signature_header: str | None) -> None:
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    expected = "sha256=" + hmac.new(
        key=settings.github_webhook_secret.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to avoid timing attacks on the signature check.
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict:
    raw_body = await request.body()
    _verify_signature(raw_body, x_hub_signature_256)

    payload = await request.json()

    if x_github_event != "pull_request":
        return {"status": "ignored", "reason": f"event type {x_github_event} not handled"}

    action = payload.get("action")
    if action not in _TRIGGER_ACTIONS:
        return {"status": "ignored", "reason": f"action '{action}' not handled"}

    pr = payload["pull_request"]
    repo = payload["repository"]
    installation = payload.get("installation")
    if not installation:
        raise HTTPException(status_code=400, detail="Webhook payload missing installation (is the GitHub App installed on this repo?)")

    pr_context = {
        "installation_id": installation["id"],
        "owner": repo["owner"]["login"],
        "repo": repo["name"],
        "pr_number": pr["number"],
        "pr_title": pr["title"],
    }

    logger.info("webhook_received", action=action, pr=pr_context)
    background_tasks.add_task(_run_review_safely, pr_context)

    return {"status": "accepted", "pr_number": pr["number"]}


async def _run_review_safely(pr_context: dict) -> None:
    """Wraps run_review so an unhandled exception doesn't just vanish into
    the BackgroundTask void — at minimum we want it logged with full context."""
    try:
        await run_review(pr_context)
    except Exception:
        logger.exception("review_pipeline_failed", pr=pr_context)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
