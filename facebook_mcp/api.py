"""Facebook Graph / Marketing API access, built on the official facebook-business SDK.

This module is the ONLY place that talks to Meta. It wraps
``facebook_business.api.FacebookAdsApi`` — the same transport the SDK's typed ad
objects use internally — behind a small uniform interface
(``get`` / ``post`` / ``delete`` / ``get_all``) that the tools call. Keeping all
network access here means:

* the SDK is imported lazily, so importing the package (and running the tests)
  never requires the SDK or network;
* tests inject a fake client with :func:`set_client`, so no tool test hits Meta;
* the auth layer is isolated. Today we authenticate with a long-lived access
  token plus App ID / App Secret (the SDK adds ``appsecret_proof`` automatically
  when the secret is present). An OAuth sign-in flow can later supply tokens
  through :func:`build_client` without changing any tool.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from typing import Any, Callable, Optional

from facebook_mcp import config as _config
from facebook_mcp.errors import GraphError


def appsecret_proof(access_token: str, app_secret: str) -> str:
    """Compute the HMAC-SHA256 appsecret_proof Meta expects for server calls."""
    return hmac.new(
        app_secret.encode("utf-8"),
        msg=access_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


class GraphClient:
    """Uniform, synchronous access to the Graph / Marketing API via the SDK."""

    def __init__(self, cfg: "_config.Config") -> None:
        self._cfg = cfg
        self._api = None  # lazily-initialised FacebookAdsApi

    # -- SDK bootstrap -----------------------------------------------------
    def _sdk(self):
        if self._api is None:
            token = self._cfg.require_token()
            try:
                from facebook_business.api import FacebookAdsApi
            except ImportError as exc:  # pragma: no cover - env-specific
                raise GraphError(
                    "facebook-business SDK is not installed; run "
                    "`pip install facebook_business`."
                ) from exc
            # FacebookAdsApi.init builds a FacebookSession; when app_secret is
            # present the session computes appsecret_proof and the SDK attaches
            # it to every call automatically.
            self._api = FacebookAdsApi.init(
                app_id=self._cfg.app_id,
                app_secret=self._cfg.app_secret,
                access_token=token,
                api_version=self._cfg.api_version,
                timeout=self._cfg.timeout,
                crash_log=False,
            )
        return self._api

    # -- low-level call ----------------------------------------------------
    def call(self, method: str, path: str, params: dict | None = None) -> Any:
        api = self._sdk()
        segments = tuple(s for s in str(path).strip("/").split("/") if s)
        try:
            resp = api.call(method.upper(), segments, params=dict(params or {}))
        except Exception as exc:  # noqa: BLE001 - normalise every SDK error
            raise _map_sdk_error(exc) from exc
        try:
            return resp.json()
        except Exception:  # pragma: no cover - non-JSON success (rare)
            body = getattr(resp, "body", None)
            return {"raw": body() if callable(body) else body}

    def get(self, path: str, params: dict | None = None) -> Any:
        return self.call("GET", path, params)

    def post(self, path: str, params: dict | None = None) -> Any:
        return self.call("POST", path, params)

    def delete(self, path: str, params: dict | None = None) -> Any:
        return self.call("DELETE", path, params)

    def get_all(self, path: str, params: dict | None = None, max_items: int = 200) -> list:
        return _paginate(self.get, path, params, max_items)


def _paginate(
    get_fn: Callable[..., Any],
    path: str,
    params: dict | None,
    max_items: int,
) -> list:
    """Follow Graph cursor pagination until max_items or the data runs out."""
    params = dict(params or {})
    items: list = []
    seen_after: set[str] = set()
    while True:
        page = get_fn(path, params)
        data = page.get("data", []) if isinstance(page, dict) else []
        items.extend(data)
        if len(items) >= max_items:
            return items[:max_items]
        paging = page.get("paging", {}) if isinstance(page, dict) else {}
        after = (paging.get("cursors") or {}).get("after")
        # Stop when there is no next page, or the cursor stops advancing.
        if not paging.get("next") or not after or after in seen_after:
            return items
        seen_after.add(after)
        params["after"] = after


def _map_sdk_error(exc: Exception) -> GraphError:
    """Map a facebook_business FacebookRequestError (or any error) to GraphError."""

    def _try(name: str, default: Any = None) -> Any:
        fn = getattr(exc, name, None)
        if callable(fn):
            try:
                return fn()
            except Exception:  # pragma: no cover
                return default
        return default

    body = _try("body")
    message = _try("api_error_message") or str(exc) or exc.__class__.__name__
    fbtrace = None
    if isinstance(body, dict):
        fbtrace = (body.get("error") or {}).get("fbtrace_id")
    return GraphError(
        message,
        status=_try("http_status", 0) or 0,
        code=_try("api_error_code"),
        subcode=_try("api_error_subcode"),
        type=_try("api_error_type"),
        fbtrace_id=fbtrace,
    )


# ---- module-level current client (set at app build; overridable in tests) ----
_client: Optional[Any] = None


def set_client(client: Any) -> None:
    """Install the active client. Tests pass a fake exposing get/post/delete/get_all."""
    global _client
    _client = client


def build_client(cfg: "_config.Config | None" = None) -> GraphClient:
    """Build and install a real GraphClient from config (OAuth-ready seam).

    A future OAuth flow can call this with a Config whose access_token was just
    minted from an authorisation code — no tool code changes.
    """
    client = GraphClient(cfg or _config.current())
    set_client(client)
    return client


def current() -> Any:
    if _client is None:
        raise GraphError("API client not initialised; call api.build_client(...) first.")
    return _client


# ---- async convenience helpers used by the tools --------------------------
async def aget(path: str, params: dict | None = None) -> Any:
    return await asyncio.to_thread(current().get, path, params or {})


async def apost(path: str, params: dict | None = None) -> Any:
    return await asyncio.to_thread(current().post, path, params or {})


async def adelete(path: str, params: dict | None = None) -> Any:
    return await asyncio.to_thread(current().delete, path, params or {})


async def aget_all(path: str, params: dict | None = None, max_items: int = 200) -> list:
    return await asyncio.to_thread(current().get_all, path, params or {}, max_items)


def dumps(obj: Any) -> str:
    """Serialise a tool result to a stable, human-readable JSON string."""
    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)
