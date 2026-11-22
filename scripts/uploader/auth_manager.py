"""Google OAuth 2.0 authentication and token manager for YouTube Data API v3.

Stores credentials and tokens securely in ~/.streamclips/auth/ outside the repository.
"""

import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Secure storage directory outside the repository
AUTH_DIR = Path.home() / ".streamclips" / "auth"
AUTH_DIR.mkdir(parents=True, exist_ok=True)

CLIENT_CONFIG_FILE = AUTH_DIR / "youtube_client_config.json"
TOKENS_FILE = AUTH_DIR / "youtube_tokens.json"

OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"

# Official YouTube upload scopes
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


class AuthManager:
    """Manages Google OAuth 2.0 flow, token caching, and automated refresh."""

    def __init__(self, redirect_uri: str = "http://127.0.0.1:5050/oauth/youtube/callback"):
        self.redirect_uri = redirect_uri
        self._state_cache: Dict[str, float] = {}

    def get_client_config(self) -> Optional[Dict[str, str]]:
        """Load client ID and client secret from secure storage."""
        if not CLIENT_CONFIG_FILE.exists():
            return None
        try:
            data = json.loads(CLIENT_CONFIG_FILE.read_text(encoding="utf-8"))
            if "installed" in data:
                data = data["installed"]
            elif "web" in data:
                data = data["web"]
            client_id = data.get("client_id")
            client_secret = data.get("client_secret")
            if client_id and client_secret:
                return {"client_id": client_id, "client_secret": client_secret}
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def save_client_config(self, client_id: str, client_secret: str) -> None:
        """Save client ID and client secret to secure storage."""
        data = {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
        }
        tmp = CLIENT_CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, CLIENT_CONFIG_FILE)

    def save_client_secrets_json(self, raw_json_content: str) -> Dict[str, str]:
        """Save imported client_secrets.json directly."""
        parsed = json.loads(raw_json_content)
        data = parsed.get("web") or parsed.get("installed") or parsed
        client_id = data.get("client_id", "").strip()
        client_secret = data.get("client_secret", "").strip()
        if not client_id or not client_secret:
            raise ValueError("Invalid client_secrets.json: missing client_id or client_secret")
        self.save_client_config(client_id, client_secret)
        return {"client_id": client_id, "client_secret": client_secret}

    def generate_auth_url(self) -> Tuple[str, str]:
        """Generate the Google OAuth consent URL with CSRF state token."""
        cfg = self.get_client_config()
        if not cfg:
            raise ValueError("Google OAuth client is not configured. Please supply Client ID and Client Secret.")

        state = secrets.token_urlsafe(24)
        self._state_cache[state] = time.time()

        params = {
            "client_id": cfg["client_id"],
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        auth_url = f"{OAUTH_AUTH_URL}?{urllib.parse.urlencode(params)}"
        return auth_url, state

    def verify_state(self, state: str) -> bool:
        """Verify that the OAuth callback state matches a recent request and invalidate it to prevent replay."""
        if not state or not isinstance(state, str):
            return False
        # Clean older states (> 15 minutes)
        now = time.time()
        self._state_cache = {k: v for k, v in self._state_cache.items() if now - v < 900}
        if state in self._state_cache:
            del self._state_cache[state]
            return True
        return False

    def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        cfg = self.get_client_config()
        if not cfg:
            raise ValueError("Google OAuth client configuration missing.")

        payload = {
            "code": code,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }

        req = urllib.request.Request(
            OAUTH_TOKEN_URL,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))

        # Calculate absolute expiration timestamp
        expires_in = token_data.get("expires_in", 3600)
        token_data["expires_at"] = time.time() + expires_in - 60  # 60s buffer

        # Fetch channel information for display
        channel_info = self._fetch_channel_info(token_data.get("access_token"))
        if channel_info:
            token_data["channel"] = channel_info

        self._save_tokens(token_data)
        return token_data

    def get_valid_access_token(self) -> str:
        """Return a valid access token, automatically refreshing if expired."""
        tokens = self.get_tokens()
        if not tokens or "refresh_token" not in tokens:
            raise PermissionError("YouTube account is not connected. Please connect YouTube first.")

        # Check expiration
        expires_at = tokens.get("expires_at", 0)
        if time.time() < expires_at and "access_token" in tokens:
            return tokens["access_token"]

        # Token is expired, refresh it
        return self._refresh_access_token(tokens["refresh_token"])

    def _refresh_access_token(self, refresh_token: str) -> str:
        """Obtain a new access token using the stored refresh token."""
        cfg = self.get_client_config()
        if not cfg:
            raise ValueError("Google OAuth client configuration missing.")

        payload = {
            "refresh_token": refresh_token,
            "client_id": cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "grant_type": "refresh_token",
        }

        req = urllib.request.Request(
            OAUTH_TOKEN_URL,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        tokens = self.get_tokens() or {}
        tokens["access_token"] = data["access_token"]
        tokens["expires_at"] = time.time() + data.get("expires_in", 3600) - 60
        if "refresh_token" in data:
            tokens["refresh_token"] = data["refresh_token"]

        self._save_tokens(tokens)
        return tokens["access_token"]

    def _fetch_channel_info(self, access_token: Optional[str]) -> Optional[Dict[str, Any]]:
        """Fetch basic YouTube channel details for the connected user."""
        if not access_token:
            return None
        try:
            req = urllib.request.Request(
                YOUTUBE_CHANNELS_URL,
                headers={"Authorization": f"Bearer {access_token}"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("items", [])
                if items:
                    snippet = items[0].get("snippet", {})
                    return {
                        "title": snippet.get("title", "YouTube Channel"),
                        "custom_url": snippet.get("customUrl", ""),
                        "avatar": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                    }
        except Exception:
            pass
        return None

    def get_tokens(self) -> Optional[Dict[str, Any]]:
        """Load stored tokens from secure storage."""
        if not TOKENS_FILE.exists():
            return None
        try:
            return json.loads(TOKENS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _save_tokens(self, tokens: Dict[str, Any]) -> None:
        """Save tokens atomically to secure storage."""
        tmp = TOKENS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
        os.replace(tmp, TOKENS_FILE)

    def clear_client_config(self) -> None:
        """Remove stored client credentials."""
        if CLIENT_CONFIG_FILE.exists():
            CLIENT_CONFIG_FILE.unlink(missing_ok=True)

    def get_status(self) -> Dict[str, Any]:
        """Return the current YouTube connection status for the UI."""
        client_cfg = self.get_client_config()
        tokens = self.get_tokens()
        has_client = client_cfg is not None
        is_connected = bool(tokens and tokens.get("refresh_token"))

        masked_client_id = None
        if client_cfg and "client_id" in client_cfg:
            cid = client_cfg["client_id"]
            if len(cid) > 20:
                masked_client_id = cid[:8] + "..." + cid[-12:]
            else:
                masked_client_id = cid[:4] + "..."

        channel = None
        if is_connected and tokens:
            channel = tokens.get("channel")

        return {
            "client_configured": has_client,
            "masked_client_id": masked_client_id,
            "connected": is_connected,
            "channel": channel,
            "storage_path": str(AUTH_DIR),
        }

    def disconnect(self) -> None:
        """Remove stored tokens and disconnect the account."""
        if TOKENS_FILE.exists():
            TOKENS_FILE.unlink(missing_ok=True)
