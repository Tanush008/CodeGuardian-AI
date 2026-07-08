"""GitHub App authentication.

A GitHub App authenticates in two steps:
1. Sign a short-lived JWT with the App's private key (proves "I am this App").
2. Exchange that JWT for an installation access token scoped to one
   installation (repo or org) — this is the token actually used for API calls.

Installation tokens expire after ~1 hour, so we cache and refresh them rather
than minting a new one per request.
"""
import time
from dataclasses import dataclass

import httpx
import jwt

from app.core.config import settings
from app.core.logging_setup import get_logger

logger = get_logger(__name__)

GITHUB_API = "https://api.github.com"


@dataclass
class _CachedToken:
    token: str
    expires_at: float  # unix timestamp


class GitHubAppAuth:
    """Handles App-level JWT signing and per-installation token caching."""

    def __init__(self) -> None:
        self._private_key: str | None = None
        self._installation_tokens: dict[int, _CachedToken] = {}

    def _load_private_key(self) -> str:
        if self._private_key is None:
            with open(settings.github_private_key_path, "r", encoding="utf-8") as f:
                self._private_key = f.read()
        return self._private_key

    def _generate_app_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 60,  # allow for clock drift
            "exp": now + (9 * 60),  # GitHub max is 10 minutes
            "iss": settings.github_app_id,
        }
        return jwt.encode(payload, self._load_private_key(), algorithm="RS256")

    async def get_installation_token(self, installation_id: int) -> str:
        """Return a cached, valid installation token, refreshing if needed."""
        cached = self._installation_tokens.get(installation_id)
        if cached and cached.expires_at - 60 > time.time():
            return cached.token

        app_jwt = self._generate_app_jwt()
        url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        expires_at = time.time() + 55 * 60  # refresh a few minutes early
        self._installation_tokens[installation_id] = _CachedToken(
            token=data["token"], expires_at=expires_at
        )
        logger.info("installation_token_refreshed", installation_id=installation_id)
        return data["token"]


github_app_auth = GitHubAppAuth()
