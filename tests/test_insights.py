"""Insights reads: date presets, time_range override, breakdowns, validation."""

from __future__ import annotations

import json

from facebook_mcp.tools import insights


async def test_account_insights_default_preset(fake, cfg_writes):
    fake.queue("GET", "act_1/insights", {"data": [{"impressions": "10"}]})
    out = json.loads(await insights.get_account_insights())
    assert out["data"][0]["impressions"] == "10"
    _, path, params = fake.last()
    assert path == "act_1/insights"
    assert params["level"] == "account"
    assert params["date_preset"] == "last_30d"


async def test_time_range_overrides_preset(fake, cfg_writes):
    fake.queue("GET", "act_1/insights", {"data": []})
    tr = '{"since":"2026-07-01","until":"2026-07-31"}'
    await insights.get_account_insights(time_range_json=tr)
    _, _, params = fake.last()
    assert "date_preset" not in params
    assert json.loads(params["time_range"]) == {"since": "2026-07-01", "until": "2026-07-31"}


async def test_unknown_preset_errors(fake, cfg_writes):
    out = json.loads(await insights.get_account_insights(date_preset="last_forever"))
    assert "date_preset" in out["error"]
    assert fake.calls == []


async def test_lifetime_maps_to_maximum(fake, cfg_writes):
    fake.queue("GET", "act_1/insights", {"data": []})
    await insights.get_account_insights(date_preset="lifetime")
    _, _, params = fake.last()
    assert params["date_preset"] == "maximum"


async def test_breakdowns_and_increment_pass_through(fake, cfg_writes):
    fake.queue("GET", "act_1/insights", {"data": []})
    await insights.get_account_insights(
        breakdowns="age,gender", time_increment="1", limit=25
    )
    _, _, params = fake.last()
    assert params["breakdowns"] == "age,gender"
    assert params["time_increment"] == "1"
    assert params["limit"] == 25


async def test_campaign_and_adset_levels(fake, cfg_writes):
    fake.queue("GET", "CMP1/insights", {"data": []})
    fake.queue("GET", "AS1/insights", {"data": []})
    await insights.get_campaign_insights("CMP1")
    assert fake.last()[1] == "CMP1/insights"
    assert fake.last()[2]["level"] == "campaign"
    await insights.get_adset_insights("AS1")
    assert fake.last()[1] == "AS1/insights"
    assert fake.last()[2]["level"] == "adset"
