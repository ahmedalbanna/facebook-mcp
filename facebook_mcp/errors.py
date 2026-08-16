"""Typed errors for the Facebook MCP server.

Every error a tool surfaces to the model is one of these; tools catch
``FacebookMCPError`` and return it as a JSON ``{"error": ...}`` payload so the
model gets a structured, actionable message instead of a stack trace.
"""

from __future__ import annotations

from typing import Any


class FacebookMCPError(Exception):
    """Base class for all errors raised by this server."""

    def as_dict(self) -> dict[str, Any]:
        return {"error": str(self)}


class ConfigError(FacebookMCPError):
    """Missing or invalid configuration (e.g. no access token)."""


class WriteDisabledError(FacebookMCPError):
    """A write tool was called while FB_ENABLE_WRITES is off."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "hint": "Set FB_ENABLE_WRITES=true to enable write operations.",
        }


class GuardrailError(FacebookMCPError):
    """A write was refused by an ads-spend or activation guardrail."""


class GraphError(FacebookMCPError):
    """A Graph API / Marketing API call returned an error.

    Carries the structured fields Meta returns so the model can react
    (e.g. distinguish an expired token from a permissions problem).
    """

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: Any = None,
        subcode: Any = None,
        type: str | None = None,
        fbtrace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.subcode = subcode
        self.type = type
        self.fbtrace_id = fbtrace_id

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": str(self)}
        for key in ("status", "code", "subcode", "type", "fbtrace_id"):
            val = getattr(self, key)
            if val not in (None, 0):
                out[key] = val
        return out
