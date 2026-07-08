"""GitHub MCP server.

Exposes a small, typed set of GitHub operations as MCP tools so the agent
graph never talks to the GitHub REST API directly. Every external action the
agents can take is one of these four tools — that's the whole audit surface.

Run standalone for local testing:
    python -m app.mcp_servers.github_mcp

In production this is invoked in-process by the agent graph via the MCP
Python SDK's stdio/session client, or exposed over SSE if you want a
separately deployed MCP process (useful once other agents/services need the
same GitHub tools).
"""
import base64

import httpx
from mcp.server.fastmcp import FastMCP

from app.core.logging_setup import configure_logging, get_logger
from app.github.app_auth import github_app_auth

configure_logging()
logger = get_logger(__name__)
GITHUB_API = "https://api.github.com"

mcp = FastMCP("codeguardian-github")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@mcp.tool()
async def list_changed_files(installation_id: int, owner: str, repo: str, pr_number: int) -> list[dict]:
    """List files changed in a pull request, with additions/deletions/status.

    Returns a list of dicts: {filename, status, additions, deletions, patch}.
    `patch` is the unified diff hunk for that file (may be None for binary
    files or very large diffs — callers must handle that).
    """
    token = await github_app_auth.get_installation_token(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/files"
    files: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as client:
        page = 1
        while True:
            resp = await client.get(url, headers=_headers(token), params={"per_page": 100, "page": page})
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            files.extend(
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "additions": f["additions"],
                    "deletions": f["deletions"],
                    "patch": f.get("patch"),
                }
                for f in batch
            )
            if len(batch) < 100:
                break
            page += 1
    logger.info("listed_changed_files", owner=owner, repo=repo, pr=pr_number, count=len(files))
    return files


@mcp.tool()
async def get_file_content(installation_id: int, owner: str, repo: str, path: str, ref: str) -> str:
    """Fetch the full text content of a file at a given ref (branch/sha).

    Used when a file's diff patch alone isn't enough context for review
    (e.g. checking whether a changed function is covered elsewhere, or
    pulling the whole file for RAG-grounded quality review).
    """
    token = await github_app_auth.get_installation_token(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers=_headers(token), params={"ref": ref})
        resp.raise_for_status()
        data = resp.json()

    if data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return data.get("content", "")


@mcp.tool()
async def get_pr_diff(installation_id: int, owner: str, repo: str, pr_number: int) -> str:
    """Fetch the full unified diff for a pull request as raw text."""
    token = await github_app_auth.get_installation_token(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = _headers(token)
    headers["Accept"] = "application/vnd.github.v3.diff"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.text


@mcp.tool()
async def post_review_comment(installation_id: int, owner: str, repo: str, pr_number: int, body_markdown: str) -> dict:
    """Post the aggregated review report as a single PR issue comment.

    Uses the issue-comments endpoint (top-level PR comment) rather than a
    line-anchored review comment for v1 — simpler and always succeeds even
    if diff line-mapping is imperfect. Returns {id, html_url}.
    """
    token = await github_app_auth.get_installation_token(installation_id)
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments"
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, headers=_headers(token), json={"body": body_markdown})
        resp.raise_for_status()
        data = resp.json()
    logger.info("posted_review_comment", owner=owner, repo=repo, pr=pr_number, comment_id=data["id"])
    return {"id": data["id"], "html_url": data["html_url"]}


if __name__ == "__main__":
    mcp.run()
