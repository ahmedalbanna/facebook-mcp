"""Tool behaviour: reads, write-gating, ads guardrails, payloads, registration."""

from __future__ import annotations

import asyncio
import json

from facebook_mcp import app as appmod
from facebook_mcp import config
from facebook_mcp.tools import ads, common, instagram, messenger, pages


async def test_whoami_reads_me(fake, cfg_writes):
    fake.queue("GET", "me", {"id": "1", "name": "Me"})
    out = json.loads(await common.whoami())
    assert out["name"] == "Me"
    assert fake.last()[:2] == ("GET", "me")


async def test_list_pages_paginates(fake, cfg_writes):
    fake.queue(
        "GET",
        "me/accounts",
        {"data": [{"id": "P1"}], "paging": {"next": "u", "cursors": {"after": "A"}}},
        {"data": [{"id": "P2"}], "paging": {}},
    )
    out = json.loads(await pages.list_pages())
    assert [p["id"] for p in out["data"]] == ["P1", "P2"]


async def test_create_page_post_blocked_when_readonly(fake, cfg_readonly):
    out = json.loads(await pages.create_page_post("hi"))
    assert "disabled" in out["error"].lower()
    assert fake.calls == []  # never hit the API


async def test_create_page_post_uses_default_page(fake, cfg_writes):
    fake.queue("POST", "PAGE/feed", {"id": "POST1"})
    out = json.loads(await pages.create_page_post("hello", link="http://x"))
    assert out["id"] == "POST1"
    method, path, params = fake.last()
    assert (method, path) == ("POST", "PAGE/feed")
    assert params["message"] == "hello" and params["link"] == "http://x"


async def test_create_campaign_active_blocked(fake, cfg_writes):
    out = json.loads(await ads.create_campaign("C", "OUTCOME_TRAFFIC", status="ACTIVE"))
    assert "FB_ADS_ALLOW_ACTIVATE" in out["error"]
    assert fake.calls == []


async def test_create_campaign_budget_without_cap_refused(fake, cfg_writes):
    out = json.loads(await ads.create_campaign("C", "OUTCOME_TRAFFIC", daily_budget=500))
    assert "cap" in out["error"].lower()
    assert fake.calls == []


async def test_create_campaign_paused_within_cap(fake, cfg_writes):
    cfg_writes.ads_max_daily_budget = 1000
    fake.queue("POST", "act_1/campaigns", {"id": "CMP1"})
    out = json.loads(await ads.create_campaign("C", "OUTCOME_TRAFFIC", daily_budget=500))
    assert out["id"] == "CMP1"
    _, path, params = fake.last()
    assert path == "act_1/campaigns"
    assert params["status"] == "PAUSED"
    assert params["daily_budget"] == 500


async def test_dry_run_previews_instead_of_calling(fake):
    config.set_config(
        config.Config(access_token="t", enable_writes=True, dry_run=True, page_id="PAGE")
    )
    try:
        out = json.loads(await pages.create_page_post("hi"))
        assert out["dry_run"] is True
        assert out["would_call"]["path"] == "PAGE/feed"
        assert fake.calls == []
    finally:
        config._config = None


async def test_messenger_send_builds_payload(fake, cfg_writes):
    fake.queue("POST", "PAGE/messages", {"message_id": "m1"})
    out = json.loads(await messenger.send_message("PSID", "hey"))
    assert out["message_id"] == "m1"
    _, path, params = fake.last()
    assert path == "PAGE/messages"
    assert json.loads(params["recipient"]) == {"id": "PSID"}
    assert json.loads(params["message"]) == {"text": "hey"}


async def test_ig_publish_photo_two_step(fake, cfg_writes):
    fake.queue("POST", "IG/media", {"id": "CID"})
    fake.queue("POST", "IG/media_publish", {"id": "MID"})
    out = json.loads(await instagram.publish_ig_photo("http://img", caption="c"))
    assert out["container"]["id"] == "CID"
    assert out["published"]["id"] == "MID"
    assert [(m, p) for m, p, _ in fake.calls] == [
        ("POST", "IG/media"),
        ("POST", "IG/media_publish"),
    ]


async def test_fb_get_generic(fake, cfg_readonly):
    fake.queue("GET", "me/accounts", {"data": [{"id": "P"}]})
    out = json.loads(await common.fb_get("me/accounts", '{"fields":"id"}'))
    assert out["data"][0]["id"] == "P"


async def test_missing_default_id_is_clear_error(fake):
    config.set_config(config.Config(access_token="t", enable_writes=True))  # no page_id
    try:
        out = json.loads(await pages.create_page_post("hi"))
        assert "FB_PAGE_ID" in out["error"]
        assert fake.calls == []
    finally:
        config._config = None


def test_registration_gates_writes():
    ro = appmod.build_app(config.Config(access_token="t", enable_writes=False))
    ro_names = {t.name for t in asyncio.run(ro.list_tools())}
    config._config = None
    assert "list_pages" in ro_names
    assert "whoami" in ro_names
    assert "create_page_post" not in ro_names
    assert "send_message" not in ro_names

    rw = appmod.build_app(config.Config(access_token="t", enable_writes=True))
    rw_names = {t.name for t in asyncio.run(rw.list_tools())}
    config._config = None
    assert "create_page_post" in rw_names
    assert "create_campaign" in rw_names
    assert "send_message" in rw_names
