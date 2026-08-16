"""Insights reads for accounts, campaigns and ad sets.

These complement the generic ``get_ad_insights`` in :mod:`facebook_mcp.tools.ads`
by adding a validated ``date_preset``, an explicit ``time_range`` (since/until),
``breakdowns`` (e.g. age, gender, country, publisher_platform) and
``time_increment`` (daily/weekly/monthly time series).
"""

from __future__ import annotations

import json

from facebook_mcp import api
from facebook_mcp.errors import FacebookMCPError
from facebook_mcp.tools.ads import _acct
from facebook_mcp.tools.common import parse_params, tool

# Metrics returned by default; callers may override via the ``fields`` argument.
DEFAULT_METRICS = (
    "impressions,clicks,spend,cpc,cpm,ctr,reach,frequency,"
    "actions,cost_per_action_type"
)

# Valid Marketing API date presets (v26). "lifetime" is accepted as an alias for
# "maximum" since operators often ask for it by that name.
DATE_PRESETS = {
    "today",
    "yesterday",
    "this_week_mon_today",
    "this_week_sun_today",
    "last_week_mon_sun",
    "last_week_sun_sat",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
    "last_3d",
    "last_7d",
    "last_14d",
    "last_28d",
    "last_30d",
    "last_90d",
    "maximum",
}


def _resolve_preset(date_preset: str) -> str:
    preset = (date_preset or "").strip().lower()
    if preset == "lifetime":
        preset = "maximum"
    if preset not in DATE_PRESETS:
        raise FacebookMCPError(
            f"Unknown date_preset {date_preset!r}. Use one of: "
            f"{', '.join(sorted(DATE_PRESETS))}; or pass time_range_json."
        )
    return preset


def _build_params(
    date_preset: str,
    time_range_json: str,
    fields: str,
    level: str,
    breakdowns: str,
    time_increment: str,
    limit: int,
) -> dict:
    params: dict = {"level": level, "fields": fields}
    time_range = parse_params(time_range_json) if time_range_json else {}
    if time_range:
        params["time_range"] = json.dumps(time_range)
    else:
        params["date_preset"] = _resolve_preset(date_preset)
    if breakdowns.strip():
        params["breakdowns"] = breakdowns
    if str(time_increment).strip():
        params["time_increment"] = time_increment
    if limit:
        params["limit"] = limit
    return params


async def _insights(obj: str, level: str, **kw) -> str:
    params = _build_params(level=level, **kw)
    return api.dumps(await api.aget(f"{obj}/insights", params))


@tool
async def get_account_insights(
    ad_account_id: str = "",
    date_preset: str = "last_30d",
    time_range_json: str = "",
    fields: str = DEFAULT_METRICS,
    breakdowns: str = "",
    time_increment: str = "",
    limit: int = 0,
) -> str:
    """Account-level insights. time_range_json overrides date_preset, e.g.
    '{"since":"2026-07-01","until":"2026-07-31"}'. breakdowns is comma-separated
    (age, gender, country, publisher_platform); time_increment is 1 (daily),
    'monthly' or 'all_days'.
    """
    return await _insights(
        _acct(ad_account_id),
        "account",
        date_preset=date_preset,
        time_range_json=time_range_json,
        fields=fields,
        breakdowns=breakdowns,
        time_increment=time_increment,
        limit=limit,
    )


@tool
async def get_campaign_insights(
    campaign_id: str,
    date_preset: str = "last_30d",
    time_range_json: str = "",
    fields: str = DEFAULT_METRICS,
    breakdowns: str = "",
    time_increment: str = "",
    limit: int = 0,
) -> str:
    """Insights for one campaign (see get_account_insights for the shared args)."""
    return await _insights(
        campaign_id,
        "campaign",
        date_preset=date_preset,
        time_range_json=time_range_json,
        fields=fields,
        breakdowns=breakdowns,
        time_increment=time_increment,
        limit=limit,
    )


@tool
async def get_adset_insights(
    adset_id: str,
    date_preset: str = "last_30d",
    time_range_json: str = "",
    fields: str = DEFAULT_METRICS,
    breakdowns: str = "",
    time_increment: str = "",
    limit: int = 0,
) -> str:
    """Insights for one ad set (see get_account_insights for the shared args)."""
    return await _insights(
        adset_id,
        "adset",
        date_preset=date_preset,
        time_range_json=time_range_json,
        fields=fields,
        breakdowns=breakdowns,
        time_increment=time_increment,
        limit=limit,
    )


READ_TOOLS = [get_account_insights, get_campaign_insights, get_adset_insights]
WRITE_TOOLS: list = []
