"""Write-gating and ad-spend guardrails.

Meta's own MCP guidance warns that content pulled from Pages, comments and
messages can carry prompt-injection. So every write goes through gates:

1. :func:`require_writes` — refuse all writes unless FB_ENABLE_WRITES is set.
2. :func:`enforce_status` — ads objects are forced to PAUSED unless
   FB_ADS_ALLOW_ACTIVATE is set, so a compromised prompt cannot silently start
   live spend.
3. :func:`check_budget` — any requested budget (minor currency units) is checked
   against FB_ADS_MAX_DAILY_BUDGET / FB_ADS_MAX_LIFETIME_BUDGET, and budgeted
   writes are refused outright until a cap is configured.

:func:`maybe_dry_run` lets any write tool return a preview of the call it would
make instead of performing it, when FB_DRY_RUN is set.
"""

from __future__ import annotations

from typing import Any

from facebook_mcp.config import Config
from facebook_mcp.errors import GuardrailError, WriteDisabledError

ACTIVE_STATUSES = {"ACTIVE"}
SAFE_STATUS = "PAUSED"


def require_writes(cfg: Config) -> None:
    if not cfg.enable_writes:
        raise WriteDisabledError("Write operations are disabled on this server.")


def enforce_status(cfg: Config, requested: str | None) -> str:
    """Return a safe status, refusing activation unless explicitly allowed."""
    status = (requested or SAFE_STATUS).upper()
    if status in ACTIVE_STATUSES and not cfg.ads_allow_activate:
        raise GuardrailError(
            "Refusing to create/activate an ACTIVE ads object. Set "
            "FB_ADS_ALLOW_ACTIVATE=true to permit live spend, or use status=PAUSED."
        )
    return status


def check_budget(cfg: Config, *, daily: Any = None, lifetime: Any = None) -> None:
    """Validate requested budgets (minor units) against the configured caps."""
    for kind, value, cap in (
        ("daily", daily, cfg.ads_max_daily_budget),
        ("lifetime", lifetime, cfg.ads_max_lifetime_budget),
    ):
        if value in (None, 0, "0", ""):
            continue
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise GuardrailError(
                f"{kind}_budget must be an integer in minor units, got {value!r}."
            ) from exc
        if value < 0:
            raise GuardrailError(f"{kind}_budget must be positive (minor units).")
        env = f"FB_ADS_MAX_{kind.upper()}_BUDGET"
        if cap <= 0:
            raise GuardrailError(
                f"No {kind} budget cap configured; set {env} (minor units) before "
                f"creating or updating budgeted ads objects."
            )
        if value > cap:
            raise GuardrailError(
                f"Requested {kind} budget {value} exceeds the cap {cap} ({env})."
            )


def maybe_dry_run(cfg: Config, method: str, path: str, params: dict) -> dict | None:
    """Return a preview payload when FB_DRY_RUN is set, else None."""
    if cfg.dry_run:
        return {
            "dry_run": True,
            "would_call": {"method": method.upper(), "path": path, "params": params},
        }
    return None
