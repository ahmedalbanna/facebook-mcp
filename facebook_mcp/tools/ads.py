"""Marketing API tools: ad accounts, campaigns, ad sets, ads and insights.

Every write here is guarded (see :mod:`facebook_mcp.guardrails`): objects are
created PAUSED unless FB_ADS_ALLOW_ACTIVATE is set, and budgets are validated
against FB_ADS_MAX_DAILY_BUDGET / FB_ADS_MAX_LIFETIME_BUDGET. Budgets are in the
account's minor currency units (e.g. cents): 1000 == 10.00 in the ad account's
currency.
"""

from __future__ import annotations

import json

from facebook_mcp import api, config, guardrails
from facebook_mcp.tools.common import need, parse_params, tool

_ACCOUNT_FIELDS = (
    "account_id,name,account_status,currency,timezone_name,amount_spent,balance,spend_cap"
)
_CAMPAIGN_FIELDS = (
    "id,name,status,effective_status,objective,buying_type,"
    "daily_budget,lifetime_budget,start_time,stop_time"
)
_ADSET_FIELDS = (
    "id,name,status,effective_status,campaign_id,optimization_goal,"
    "billing_event,daily_budget,lifetime_budget"
)
_AD_FIELDS = "id,name,status,effective_status,adset_id,creative"
_INSIGHT_FIELDS = "impressions,clicks,spend,cpc,cpm,ctr,reach,frequency"


def _acct(ad_account_id: str) -> str:
    raw = need(ad_account_id, config.current().ad_account_id, "ad_account_id", "FB_AD_ACCOUNT_ID")
    return raw if raw.startswith("act_") else f"act_{raw}"


# ---- reads ----------------------------------------------------------------


@tool
async def list_ad_accounts() -> str:
    """List ad accounts the token can access (GET /me/adaccounts)."""
    data = await api.aget_all("me/adaccounts", {"fields": _ACCOUNT_FIELDS}, max_items=100)
    return api.dumps({"data": data})


@tool
async def get_ad_account(ad_account_id: str = "") -> str:
    """Get an ad account's status, currency, balance and spend cap."""
    return api.dumps(await api.aget(_acct(ad_account_id), {"fields": _ACCOUNT_FIELDS}))


@tool
async def list_campaigns(ad_account_id: str = "", limit: int = 50, after: str = "") -> str:
    """List campaigns in an ad account."""
    params = {"fields": _CAMPAIGN_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{_acct(ad_account_id)}/campaigns", params))


@tool
async def list_adsets(
    parent_id: str = "", ad_account_id: str = "", limit: int = 50, after: str = ""
) -> str:
    """List ad sets under a campaign (parent_id) or across the ad account."""
    parent = parent_id.strip() or _acct(ad_account_id)
    params = {"fields": _ADSET_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{parent}/adsets", params))


@tool
async def list_ads(
    parent_id: str = "", ad_account_id: str = "", limit: int = 50, after: str = ""
) -> str:
    """List ads under a campaign or ad set (parent_id), or across the ad account."""
    parent = parent_id.strip() or _acct(ad_account_id)
    params = {"fields": _AD_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{parent}/ads", params))


@tool
async def get_ad_insights(
    object_id: str = "",
    level: str = "account",
    date_preset: str = "last_7d",
    fields: str = _INSIGHT_FIELDS,
) -> str:
    """Read performance insights for an account/campaign/ad set/ad.

    object_id defaults to the configured ad account. level is one of
    account/campaign/adset/ad. date_preset e.g. today, last_7d, last_30d.
    """
    obj = object_id.strip() or _acct("")
    params = {"level": level, "date_preset": date_preset, "fields": fields}
    return api.dumps(await api.aget(f"{obj}/insights", params))


# ---- writes (gated by FB_ENABLE_WRITES + ad-spend guardrails) -------------


@tool
async def create_campaign(
    name: str,
    objective: str,
    ad_account_id: str = "",
    status: str = "PAUSED",
    daily_budget: int = 0,
    lifetime_budget: int = 0,
    special_ad_categories: str = "[]",
) -> str:
    """Create a campaign (PAUSED by default).

    objective uses the ODAX outcome values, e.g. OUTCOME_TRAFFIC,
    OUTCOME_ENGAGEMENT, OUTCOME_LEADS, OUTCOME_SALES, OUTCOME_AWARENESS,
    OUTCOME_APP_PROMOTION. special_ad_categories is a JSON array (use "[]" for
    none). Budgets are in minor currency units and are capped by the guardrails.
    """
    cfg = config.current()
    guardrails.require_writes(cfg)
    status = guardrails.enforce_status(cfg, status)
    guardrails.check_budget(cfg, daily=daily_budget, lifetime=lifetime_budget)
    params = {
        "name": name,
        "objective": objective,
        "status": status,
        "special_ad_categories": special_ad_categories,
    }
    if daily_budget:
        params["daily_budget"] = int(daily_budget)
    if lifetime_budget:
        params["lifetime_budget"] = int(lifetime_budget)
    path = f"{_acct(ad_account_id)}/campaigns"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def update_campaign(
    campaign_id: str,
    name: str = "",
    status: str = "",
    daily_budget: int = 0,
    lifetime_budget: int = 0,
) -> str:
    """Update a campaign's name, status or budget (guardrailed)."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    guardrails.check_budget(cfg, daily=daily_budget, lifetime=lifetime_budget)
    params: dict = {}
    if name:
        params["name"] = name
    if status:
        params["status"] = guardrails.enforce_status(cfg, status)
    if daily_budget:
        params["daily_budget"] = int(daily_budget)
    if lifetime_budget:
        params["lifetime_budget"] = int(lifetime_budget)
    if not params:
        return api.dumps({"error": "Nothing to update; provide name, status or a budget."})
    preview = guardrails.maybe_dry_run(cfg, "POST", campaign_id, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(campaign_id, params))


@tool
async def set_campaign_status(campaign_id: str, status: str) -> str:
    """Pause or activate a campaign (ACTIVE requires FB_ADS_ALLOW_ACTIVATE)."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = {"status": guardrails.enforce_status(cfg, status)}
    preview = guardrails.maybe_dry_run(cfg, "POST", campaign_id, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(campaign_id, params))


@tool
async def create_adset(
    name: str,
    campaign_id: str,
    optimization_goal: str,
    billing_event: str,
    targeting_json: str,
    ad_account_id: str = "",
    status: str = "PAUSED",
    daily_budget: int = 0,
    lifetime_budget: int = 0,
    bid_amount: int = 0,
    end_time: str = "",
) -> str:
    """Create an ad set (PAUSED by default).

    targeting_json is a JSON object, e.g.
    '{"geo_locations":{"countries":["US"]},"age_min":18}'. optimization_goal
    e.g. LINK_CLICKS, REACH, IMPRESSIONS; billing_event e.g. IMPRESSIONS,
    LINK_CLICKS. A lifetime_budget requires end_time (ISO 8601).
    """
    cfg = config.current()
    guardrails.require_writes(cfg)
    status = guardrails.enforce_status(cfg, status)
    guardrails.check_budget(cfg, daily=daily_budget, lifetime=lifetime_budget)
    targeting = parse_params(targeting_json)
    params = {
        "name": name,
        "campaign_id": campaign_id,
        "optimization_goal": optimization_goal,
        "billing_event": billing_event,
        "status": status,
        "targeting": json.dumps(targeting),
    }
    if daily_budget:
        params["daily_budget"] = int(daily_budget)
    if lifetime_budget:
        params["lifetime_budget"] = int(lifetime_budget)
    if bid_amount:
        params["bid_amount"] = int(bid_amount)
    if end_time:
        params["end_time"] = end_time
    path = f"{_acct(ad_account_id)}/adsets"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


READ_TOOLS = [
    list_ad_accounts,
    get_ad_account,
    list_campaigns,
    list_adsets,
    list_ads,
    get_ad_insights,
]
WRITE_TOOLS = [
    create_campaign,
    update_campaign,
    set_campaign_status,
    create_adset,
]
