"""Guardrails: write-gating, forced PAUSED, budget caps, dry-run preview."""

from __future__ import annotations

import pytest

from facebook_mcp import guardrails
from facebook_mcp.config import Config
from facebook_mcp.errors import GuardrailError, WriteDisabledError


def cfg(**over) -> Config:
    base = dict(enable_writes=True)
    base.update(over)
    return Config(**base)


def test_require_writes_blocks_when_disabled():
    with pytest.raises(WriteDisabledError):
        guardrails.require_writes(cfg(enable_writes=False))
    guardrails.require_writes(cfg(enable_writes=True))  # no raise


def test_enforce_status_defaults_to_paused():
    assert guardrails.enforce_status(cfg(), None) == "PAUSED"
    assert guardrails.enforce_status(cfg(), "paused") == "PAUSED"


def test_enforce_status_blocks_active_without_flag():
    with pytest.raises(GuardrailError):
        guardrails.enforce_status(cfg(ads_allow_activate=False), "ACTIVE")


def test_enforce_status_allows_active_with_flag():
    assert guardrails.enforce_status(cfg(ads_allow_activate=True), "ACTIVE") == "ACTIVE"


def test_check_budget_requires_configured_cap():
    with pytest.raises(GuardrailError):
        guardrails.check_budget(cfg(ads_max_daily_budget=0), daily=100)


def test_check_budget_enforces_cap():
    with pytest.raises(GuardrailError):
        guardrails.check_budget(cfg(ads_max_daily_budget=50), daily=100)
    guardrails.check_budget(cfg(ads_max_daily_budget=200), daily=100)  # within cap


def test_check_budget_ignores_zero_and_none():
    guardrails.check_budget(cfg(), daily=0, lifetime=None)  # no raise


def test_maybe_dry_run():
    assert guardrails.maybe_dry_run(cfg(dry_run=False), "POST", "x", {}) is None
    preview = guardrails.maybe_dry_run(cfg(dry_run=True), "POST", "x", {"a": 1})
    assert preview["dry_run"] is True
    assert preview["would_call"]["method"] == "POST"
    assert preview["would_call"]["path"] == "x"
