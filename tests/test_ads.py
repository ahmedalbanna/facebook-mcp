"""Ads build-out: single-object reads, budget/status guardrails, creatives, media."""

from __future__ import annotations

import base64
import json

from facebook_mcp.tools import ads


async def test_get_campaign_reads_fields(fake, cfg_writes):
    fake.queue("GET", "CMP1", {"id": "CMP1", "objective": "OUTCOME_TRAFFIC"})
    out = json.loads(await ads.get_campaign("CMP1"))
    assert out["objective"] == "OUTCOME_TRAFFIC"
    method, path, params = fake.last()
    assert (method, path) == ("GET", "CMP1")
    assert "objective" in params["fields"]


async def test_get_adset_requests_targeting(fake, cfg_writes):
    fake.queue("GET", "AS1", {"id": "AS1"})
    await ads.get_adset("AS1")
    _, path, params = fake.last()
    assert path == "AS1"
    assert "targeting" in params["fields"]


async def test_get_ad_reads(fake, cfg_writes):
    fake.queue("GET", "AD1", {"id": "AD1", "adset_id": "AS1"})
    out = json.loads(await ads.get_ad("AD1"))
    assert out["adset_id"] == "AS1"


async def test_delete_campaign_blocked_when_readonly(fake, cfg_readonly):
    out = json.loads(await ads.delete_campaign("CMP1"))
    assert "disabled" in out["error"].lower()
    assert fake.calls == []


async def test_delete_campaign_deletes(fake, cfg_writes):
    fake.queue("DELETE", "CMP1", {"success": True})
    out = json.loads(await ads.delete_campaign("CMP1"))
    assert out["success"] is True
    assert fake.last()[:2] == ("DELETE", "CMP1")


async def test_update_campaign_budget_needs_a_budget(fake, cfg_writes):
    cfg_writes.ads_max_daily_budget = 1000
    out = json.loads(await ads.update_campaign_budget("CMP1"))
    assert "budget" in out["error"].lower()
    assert fake.calls == []


async def test_update_campaign_budget_over_cap_refused(fake, cfg_writes):
    cfg_writes.ads_max_daily_budget = 1000
    out = json.loads(await ads.update_campaign_budget("CMP1", daily_budget=5000))
    assert "exceeds" in out["error"].lower()
    assert fake.calls == []


async def test_update_campaign_budget_within_cap(fake, cfg_writes):
    cfg_writes.ads_max_daily_budget = 1000
    fake.queue("POST", "CMP1", {"success": True})
    out = json.loads(await ads.update_campaign_budget("CMP1", daily_budget=500))
    assert out["success"] is True
    _, path, params = fake.last()
    assert path == "CMP1"
    assert params["daily_budget"] == 500


async def test_update_adset_status_active_blocked(fake, cfg_writes):
    out = json.loads(await ads.update_adset_status("AS1", "ACTIVE"))
    assert "FB_ADS_ALLOW_ACTIVATE" in out["error"]
    assert fake.calls == []


async def test_update_adset_status_paused(fake, cfg_writes):
    fake.queue("POST", "AS1", {"success": True})
    await ads.update_adset_status("AS1", "paused")
    _, path, params = fake.last()
    assert path == "AS1"
    assert params["status"] == "PAUSED"


async def test_update_adset_targeting_serializes_json(fake, cfg_writes):
    fake.queue("POST", "AS1", {"success": True})
    await ads.update_adset_targeting("AS1", '{"geo_locations":{"countries":["US"]}}')
    _, path, params = fake.last()
    assert path == "AS1"
    assert json.loads(params["targeting"]) == {"geo_locations": {"countries": ["US"]}}


async def test_create_ad_builds_creative_ref(fake, cfg_writes):
    fake.queue("POST", "act_1/ads", {"id": "AD1"})
    out = json.loads(await ads.create_ad("Ad", "AS1", "CR1"))
    assert out["id"] == "AD1"
    _, path, params = fake.last()
    assert path == "act_1/ads"
    assert params["status"] == "PAUSED"
    assert json.loads(params["creative"]) == {"creative_id": "CR1"}


async def test_update_ad_status_active_blocked(fake, cfg_writes):
    out = json.loads(await ads.update_ad_status("AD1", "ACTIVE"))
    assert "FB_ADS_ALLOW_ACTIVATE" in out["error"]
    assert fake.calls == []


async def test_create_ad_creative_wraps_spec(fake, cfg_writes):
    fake.queue("POST", "act_1/adcreatives", {"id": "CR1"})
    spec = '{"page_id":"PAGE","link_data":{"link":"http://x"}}'
    out = json.loads(await ads.create_ad_creative("Creative", spec))
    assert out["id"] == "CR1"
    _, path, params = fake.last()
    assert path == "act_1/adcreatives"
    assert json.loads(params["object_story_spec"])["page_id"] == "PAGE"


async def test_create_link_ad_creative_builds_story_spec(fake, cfg_writes):
    fake.queue("POST", "act_1/adcreatives", {"id": "CR2"})
    out = json.loads(
        await ads.create_link_ad_creative(
            "LinkAd",
            "http://landing",
            message="Buy now",
            image_hash="HASH",
            call_to_action_type="SHOP_NOW",
        )
    )
    assert out["id"] == "CR2"
    _, path, params = fake.last()
    assert path == "act_1/adcreatives"
    spec = json.loads(params["object_story_spec"])
    assert spec["page_id"] == "PAGE"  # from cfg default
    link_data = spec["link_data"]
    assert link_data["link"] == "http://landing"
    assert link_data["message"] == "Buy now"
    assert link_data["image_hash"] == "HASH"
    assert link_data["call_to_action"] == {
        "type": "SHOP_NOW",
        "value": {"link": "http://landing"},
    }


async def test_create_link_ad_creative_needs_page(fake):
    from facebook_mcp import config

    config.set_config(config.Config(access_token="t", enable_writes=True, ad_account_id="act_1"))
    try:
        out = json.loads(await ads.create_link_ad_creative("A", "http://x"))
        assert "FB_PAGE_ID" in out["error"]
        assert fake.calls == []
    finally:
        config._config = None


async def test_upload_ad_image_base64_encodes(fake, cfg_writes, tmp_path):
    img = tmp_path / "pic.png"
    raw = b"\x89PNG\r\n\x1a\n binary-bytes"
    img.write_bytes(raw)
    fake.queue("POST", "act_1/adimages", {"images": {"pic.png": {"hash": "H1"}}})
    out = json.loads(await ads.upload_ad_image(str(img)))
    assert out["images"]["pic.png"]["hash"] == "H1"
    _, path, params = fake.last()
    assert path == "act_1/adimages"
    assert base64.b64decode(params["bytes"]) == raw  # exactly the file bytes


async def test_upload_ad_image_missing_file(fake, cfg_writes):
    out = json.loads(await ads.upload_ad_image("/no/such/file.png"))
    assert "could not read" in out["error"].lower()
    assert fake.calls == []


async def test_upload_ad_image_dry_run_redacts_bytes(fake, tmp_path):
    from facebook_mcp import config

    img = tmp_path / "pic.png"
    img.write_bytes(b"abcde")
    config.set_config(
        config.Config(access_token="t", enable_writes=True, dry_run=True, ad_account_id="act_1")
    )
    try:
        out = json.loads(await ads.upload_ad_image(str(img)))
        assert out["dry_run"] is True
        # the raw base64 is never surfaced in the preview
        assert "base64" in out["would_call"]["params"]["bytes"]
        assert "abcde" not in out["would_call"]["params"]["bytes"]
        assert fake.calls == []
    finally:
        config._config = None


async def test_upload_ad_video_requires_url(fake, cfg_writes):
    out = json.loads(await ads.upload_ad_video("   "))
    assert "required" in out["error"].lower()
    assert fake.calls == []


async def test_upload_ad_video_posts_file_url(fake, cfg_writes):
    fake.queue("POST", "act_1/advideos", {"id": "V1"})
    out = json.loads(await ads.upload_ad_video("http://host/v.mp4"))
    assert out["id"] == "V1"
    _, path, params = fake.last()
    assert path == "act_1/advideos"
    assert params["file_url"] == "http://host/v.mp4"
