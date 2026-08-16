"""Publishing: Page photos & scheduled posts, IG video/reel/story with polling."""

from __future__ import annotations

import json

from facebook_mcp import config
from facebook_mcp.tools import instagram, pages

# ---- Pages ----------------------------------------------------------------


async def test_publish_page_photo(fake, cfg_writes):
    fake.queue("POST", "PAGE/photos", {"id": "PH1"})
    out = json.loads(await pages.publish_page_photo("http://img", caption="hi"))
    assert out["id"] == "PH1"
    _, path, params = fake.last()
    assert path == "PAGE/photos"
    assert params["url"] == "http://img"
    assert params["caption"] == "hi"
    assert params["published"] is True


async def test_schedule_page_post(fake, cfg_writes):
    fake.queue("POST", "PAGE/feed", {"id": "S1"})
    out = json.loads(await pages.schedule_page_post("later", 1893456000))
    assert out["id"] == "S1"
    _, path, params = fake.last()
    assert path == "PAGE/feed"
    assert params["published"] is False
    assert params["scheduled_publish_time"] == 1893456000


async def test_schedule_page_post_rejects_bad_time(fake, cfg_writes):
    out = json.loads(await pages.schedule_page_post("later", 0))
    assert "timestamp" in out["error"].lower()
    assert fake.calls == []


async def test_publish_page_photo_blocked_readonly(fake, cfg_readonly):
    out = json.loads(await pages.publish_page_photo("http://img"))
    assert "disabled" in out["error"].lower()
    assert fake.calls == []


# ---- Instagram video / reel / story --------------------------------------


async def test_publish_ig_video_polls_then_publishes(fake, cfg_writes, monkeypatch):
    monkeypatch.setattr(instagram, "_CONTAINER_POLL_DELAY", 0)
    fake.queue("POST", "IG/media", {"id": "CID"})
    fake.queue("GET", "CID", {"status_code": "FINISHED"})
    fake.queue("POST", "IG/media_publish", {"id": "MID"})
    out = json.loads(await instagram.publish_ig_video("http://v.mp4", caption="c"))
    assert out["container"]["id"] == "CID"
    assert out["published"]["id"] == "MID"
    # container request carried the VIDEO media_type
    first = fake.calls[0]
    assert first[1] == "IG/media"
    assert first[2]["media_type"] == "VIDEO"


async def test_publish_ig_reel_sets_reels_type(fake, cfg_writes, monkeypatch):
    monkeypatch.setattr(instagram, "_CONTAINER_POLL_DELAY", 0)
    fake.queue("POST", "IG/media", {"id": "RID"})
    fake.queue("GET", "RID", {"status_code": "FINISHED"})
    fake.queue("POST", "IG/media_publish", {"id": "RPUB"})
    out = json.loads(await instagram.publish_ig_reel("http://v.mp4", share_to_feed=False))
    assert out["published"]["id"] == "RPUB"
    params = fake.calls[0][2]
    assert params["media_type"] == "REELS"
    assert params["share_to_feed"] is False


async def test_publish_ig_video_pending_when_not_ready(fake, cfg_writes, monkeypatch):
    monkeypatch.setattr(instagram, "_CONTAINER_POLL_DELAY", 0)
    monkeypatch.setattr(instagram, "_CONTAINER_POLL_TRIES", 3)
    fake.queue("POST", "IG/media", {"id": "CID"})
    fake.queue("GET", "CID", {"status_code": "IN_PROGRESS"})  # never finishes
    out = json.loads(await instagram.publish_ig_video("http://v.mp4"))
    assert out["pending"] is True
    assert out["creation_id"] == "CID"
    # never attempted to publish
    assert all(p != "IG/media_publish" for _, p, _ in fake.calls)


async def test_publish_ig_story_image_no_poll(fake, cfg_writes):
    fake.queue("POST", "IG/media", {"id": "SID"})
    fake.queue("POST", "IG/media_publish", {"id": "SPUB"})
    out = json.loads(await instagram.publish_ig_story(image_url="http://img.jpg"))
    assert out["published"]["id"] == "SPUB"
    params = fake.calls[0][2]
    assert params["media_type"] == "STORIES"
    assert params["image_url"] == "http://img.jpg"
    # image stories don't poll for status
    assert all(m != "GET" for m, _, _ in fake.calls)


async def test_publish_ig_story_requires_exactly_one_source(fake, cfg_writes):
    out = json.loads(
        await instagram.publish_ig_story(image_url="http://img", video_url="http://v")
    )
    assert "exactly one" in out["error"].lower()
    assert fake.calls == []


async def test_publish_ig_video_dry_run(fake, monkeypatch):
    config.set_config(
        config.Config(access_token="t", enable_writes=True, dry_run=True, ig_user_id="IG")
    )
    try:
        out = json.loads(await instagram.publish_ig_video("http://v.mp4"))
        assert out["dry_run"] is True
        assert len(out["would_call"]) == 2
        assert fake.calls == []
    finally:
        config._config = None


async def test_get_ig_media_insights(fake, cfg_writes):
    fake.queue("GET", "MID/insights", {"data": [{"name": "reach", "values": [{"value": 5}]}]})
    out = json.loads(await instagram.get_ig_media_insights("MID"))
    assert out["data"][0]["name"] == "reach"
    assert fake.last()[1] == "MID/insights"


async def test_get_ig_container_status(fake, cfg_writes):
    fake.queue("GET", "CID", {"status_code": "FINISHED"})
    out = json.loads(await instagram.get_ig_container_status("CID"))
    assert out["status_code"] == "FINISHED"
