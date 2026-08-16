"""Automated ad rules (adrules_library).

Ad rules run unattended, so a rule whose action resumes or raises spend is
exactly the "silent live spend" the guardrails guard against. Creating such a
rule (execution_type UNPAUSE, CHANGE_BUDGET, ...) therefore requires
FB_ADS_ALLOW_ACTIVATE, the same flag that gates activating ads directly. Rules
that only pause or notify are allowed whenever writes are enabled.
"""

from __future__ import annotations

import json

from facebook_mcp import api, config, guardrails
from facebook_mcp.errors import GuardrailError
from facebook_mcp.tools.ads import _acct
from facebook_mcp.tools.common import parse_params, tool

_RULE_FIELDS = "id,name,status,evaluation_spec,execution_spec,schedule_spec,created_time"

# Execution types that can start or increase spend if the rule fires.
_SPEND_EXECUTION = {"UNPAUSE", "CHANGE_BUDGET", "REBALANCE_BUDGET", "INCREASE_BUDGET"}


@tool
async def list_auto_rules(ad_account_id: str = "", limit: int = 50, after: str = "") -> str:
    """List the automated rules in an ad account."""
    params = {"fields": _RULE_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{_acct(ad_account_id)}/adrules_library", params))


@tool
async def create_auto_rule(
    name: str,
    evaluation_spec_json: str,
    execution_spec_json: str,
    schedule_spec_json: str = "",
    status: str = "ENABLED",
    ad_account_id: str = "",
) -> str:
    """Create an automated ad rule.

    evaluation_spec_json e.g. '{"evaluation_type":"SCHEDULE","filters":[{"field":
    "spent","operator":"GREATER_THAN","value":10000}]}'. execution_spec_json e.g.
    '{"execution_type":"PAUSE"}'. Rules that resume or raise spend (UNPAUSE,
    CHANGE_BUDGET, REBALANCE_BUDGET, INCREASE_BUDGET) require FB_ADS_ALLOW_ACTIVATE.
    """
    cfg = config.current()
    guardrails.require_writes(cfg)
    evaluation = parse_params(evaluation_spec_json)
    execution = parse_params(execution_spec_json)
    exec_type = str(execution.get("execution_type", "")).upper()
    if exec_type in _SPEND_EXECUTION and not cfg.ads_allow_activate:
        raise GuardrailError(
            f"Refusing to create a rule with execution_type={exec_type} that can resume "
            "or raise ad spend. Set FB_ADS_ALLOW_ACTIVATE=true to permit it."
        )
    params = {
        "name": name,
        "evaluation_spec": json.dumps(evaluation),
        "execution_spec": json.dumps(execution),
        "status": status.upper(),
    }
    if schedule_spec_json.strip():
        params["schedule_spec"] = json.dumps(parse_params(schedule_spec_json))
    path = f"{_acct(ad_account_id)}/adrules_library"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def delete_auto_rule(rule_id: str) -> str:
    """Delete an automated ad rule."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    preview = guardrails.maybe_dry_run(cfg, "DELETE", rule_id, {})
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.adelete(rule_id, {}))


READ_TOOLS = [list_auto_rules]
WRITE_TOOLS = [create_auto_rule, delete_auto_rule]
