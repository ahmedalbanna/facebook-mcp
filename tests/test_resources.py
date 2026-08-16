"""Resources and prompts: backing data functions, prompt text, registration."""

from __future__ import annotations

import json

from facebook_mcp import app as appmod
from facebook_mcp import config


async def test_resource_active_campaigns(fake, cfg_writes):
    fake.queue("GET", "act_1/campaigns", {"data": [{"id": "C1", "status": "ACTIVE"}]})
    out = json.loads(await appmod.resource_active_campaigns())
    assert out["data"][0]["id"] == "C1"
    _, path, params = fake.last()
    assert path == "act_1/campaigns"
    assert params["effective_status"] == '["ACTIVE"]'


async def test_resource_account_summary(fake, cfg_writes):
    fake.queue("GET", "act_1/insights", {"data": [{"spend": "12"}]})
    out = json.loads(await appmod.resource_account_summary())
    assert out["data"][0]["spend"] == "12"
    assert fake.last()[2]["level"] == "account"


async def test_resource_audiences_list(fake, cfg_writes):
    fake.queue("GET", "act_1/customaudiences", {"data": [{"id": "AUD1"}]})
    out = json.loads(await appmod.resource_audiences_list())
    assert out["data"][0]["id"] == "AUD1"
    assert fake.last()[1] == "act_1/customaudiences"


def test_ad_copy_prompt_text():
    text = appmod.ad_copy_prompt("Trail Shoes", audience="runners", tone="bold", count=2)
    assert "2 distinct" in text
    assert "runners" in text
    assert "Meta" in text  # policy reminder present


def test_marketing_report_prompt_text():
    text = appmod.marketing_report_prompt(period="last_7d", focus="CPC")
    assert "last_7d" in text
    assert "generate_account_summary" in text
    assert "CPC" in text


async def test_resources_and_prompts_registered():
    cfg = config.Config(access_token="t", enable_writes=True, ad_account_id="act_1")
    app = appmod.build_app(cfg)
    config._config = None
    uris = {str(r.uri) for r in await app.list_resources()}
    names = {p.name for p in await app.list_prompts()}
    assert uris == {"campaigns://active", "account://summary", "audiences://list"}
    assert names == {"ad_copy_prompt", "marketing_report_prompt"}
