"""Shared tool helpers plus generic / diagnostic tools.

The :func:`tool` decorator wraps every tool so a raised ``FacebookMCPError``
becomes a JSON ``{"error": ...}`` string instead of a stack trace — the model
gets a structured, actionable result either way. It preserves the wrapped
function's signature and docstring so FastMCP builds the right input schema.
"""

from __future__ import annotations

import functools
import inspect
import json
from typing import Any, Callable

from facebook_mcp import api, config, guardrails
from facebook_mcp.errors import ConfigError, FacebookMCPError


def tool(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an async tool so any FacebookMCPError becomes a JSON error string."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return await fn(*args, **kwargs)
        except FacebookMCPError as exc:
            return api.dumps(exc.as_dict())

    # Guarantee FastMCP sees the real parameter list even if it does not follow
    # __wrapped__ when building the tool's input schema.
    wrapper.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
    return wrapper


def parse_params(params_json: str | dict | None) -> dict:
    """Parse a JSON object argument into a dict; tolerate an already-parsed dict."""
    if params_json is None or params_json == "":
        return {}
    if isinstance(params_json, dict):
        return params_json
    try:
        parsed = json.loads(params_json)
    except (TypeError, ValueError) as exc:
        raise FacebookMCPError(f"Invalid JSON in params: {exc}") from exc
    if not isinstance(parsed, dict):
        raise FacebookMCPError("params must be a JSON object.")
    return parsed


def need(value: str | None, fallback: str | None, label: str, env: str) -> str:
    """Return an explicit value, else a configured default, else a clear error."""
    resolved = (value or "").strip() or (fallback or "")
    if not resolved:
        raise ConfigError(
            f"No {label} given and none configured. Pass it explicitly or set {env}."
        )
    return resolved


def token_override(cfg: config.Config, access_token: str) -> dict:
    """Params that override the session token, with a matching appsecret_proof.

    Computing the proof over the token we actually send keeps calls valid whether
    or not the app has "require app secret proof" enabled.
    """
    params: dict[str, Any] = {"access_token": access_token}
    if cfg.app_secret:
        params["appsecret_proof"] = api.appsecret_proof(access_token, cfg.app_secret)
    return params


# ---------------------------------------------------------------------------
# Generic / diagnostic tools
# ---------------------------------------------------------------------------


@tool
async def whoami() -> str:
    """Return the identity behind the configured access token (GET /me)."""
    data = await api.aget("me", {"fields": "id,name"})
    return api.dumps(data)


@tool
async def debug_token(input_token: str = "") -> str:
    """Inspect an access token: app id, scopes, type and expiry (GET /debug_token).

    With no argument, inspects the server's own configured token. Uses the app
    access token (app_id|app_secret) when app credentials are configured.
    """
    cfg = config.current()
    token = input_token.strip() or cfg.require_token()
    params: dict[str, Any] = {"input_token": token}
    if cfg.app_id and cfg.app_secret:
        params.update(token_override(cfg, f"{cfg.app_id}|{cfg.app_secret}"))
    data = await api.aget("debug_token", params)
    return api.dumps(data)


@tool
async def fb_get(path: str, params_json: str = "") -> str:
    """Generic read: GET any Graph API path with an optional JSON params object.

    Escape hatch for endpoints without a dedicated tool, e.g.
    path="me/accounts", params_json='{"fields":"name,access_token"}'.
    """
    return api.dumps(await api.aget(path, parse_params(params_json)))


@tool
async def fb_post(path: str, params_json: str = "") -> str:
    """Generic write: POST any Graph API path (gated by FB_ENABLE_WRITES)."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = parse_params(params_json)
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def fb_delete(path: str, params_json: str = "") -> str:
    """Generic write: DELETE any Graph API path (gated by FB_ENABLE_WRITES)."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = parse_params(params_json)
    preview = guardrails.maybe_dry_run(cfg, "DELETE", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.adelete(path, params))


READ_TOOLS = [whoami, debug_token, fb_get]
WRITE_TOOLS = [fb_post, fb_delete]
