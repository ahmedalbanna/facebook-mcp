"""Media-viewing tools: SSRF guard, inline Image content, and sandboxed saves.

All network access goes through media._http_get, which these tests monkeypatch,
so nothing here touches the network or a real CDN.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp.utilities.types import Image

from facebook_mcp import app as appmod
from facebook_mcp import config
from facebook_mcp.tools import media

# 1x1 PNG and a minimal JPEG header — enough for the magic-byte sniffer.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x00\x03\x00\x01\xd3\x10\xf1\x1e\x00\x00\x00\x00IEND\xaeB`\x82"
)
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 16


def _fetch_returning(payload: bytes, ctype: str, sink: list | None = None):
    async def _fake(url: str, max_bytes: int):
        if sink is not None:
            sink.append((url, max_bytes))
        return payload, ctype

    return _fake


# ---- SSRF guard (pure, no fixtures) ---------------------------------------


def test_check_url_allows_meta_hosts():
    for url in (
        "https://scontent-lhr8-1.xx.fbcdn.net/v/t51/photo.jpg",
        "https://video-lhr6-2.xx.fbcdn.net/v/reel.mp4",
        "https://scontent.cdninstagram.com/v/t51/img.jpg",
        "https://lookaside.fbsbx.com/attachment?id=1",
        "https://graph.facebook.com/v26.0/123/picture",
        "http://instagram.com/p/abc/media",
    ):
        media._check_url(url)  # must not raise


def test_check_url_blocks_foreign_internal_and_lookalike():
    from facebook_mcp.errors import FacebookMCPError

    bad = [
        "https://example.com/x.jpg",  # not a Meta host
        "https://evilfbcdn.net/x.jpg",  # lookalike, not a subdomain of fbcdn.net
        "https://notfbcdn.net.attacker.com/x.jpg",  # suffix trick
        "http://169.254.169.254/latest/meta-data",  # cloud metadata
        "http://127.0.0.1/x",  # loopback
        "http://localhost/x",  # non-Meta host
        "http://10.0.0.5/x",  # private
        "https://8.8.8.8/x",  # raw public IP still refused
        "file:///etc/passwd",  # non-http scheme
        "ftp://scontent.xx.fbcdn.net/x",  # non-http scheme
    ]
    for url in bad:
        with pytest.raises(FacebookMCPError):
            media._check_url(url)


# ---- view_image -----------------------------------------------------------


async def test_view_image_returns_inline_image(monkeypatch):
    monkeypatch.setattr(media, "_http_get", _fetch_returning(PNG, "image/png"))
    out = await media.view_image("https://scontent.xx.fbcdn.net/p.png")
    assert isinstance(out, Image)
    assert out.to_image_content().mimeType == "image/png"


async def test_view_image_sniffs_over_lying_content_type(monkeypatch):
    # Header claims octet-stream but the bytes are a JPEG: sniffing wins.
    monkeypatch.setattr(media, "_http_get", _fetch_returning(JPEG, "application/octet-stream"))
    out = await media.view_image("https://scontent.xx.fbcdn.net/p")
    assert isinstance(out, Image)
    assert out.to_image_content().mimeType == "image/jpeg"


async def test_view_image_rejects_internal_host():
    # No monkeypatch: the SSRF guard must reject before any fetch happens.
    out = await media.view_image("http://169.254.169.254/latest/meta-data")
    assert isinstance(out, str)
    assert "private" in json.loads(out)["error"].lower()


async def test_view_image_non_image_errors(monkeypatch):
    monkeypatch.setattr(media, "_http_get", _fetch_returning(b"<html>nope", "text/html"))
    out = await media.view_image("https://scontent.xx.fbcdn.net/page")
    assert isinstance(out, str)
    assert "image" in json.loads(out)["error"].lower()


# ---- view_ig_media --------------------------------------------------------


async def test_view_ig_media_photo(fake, monkeypatch):
    seen: list = []
    monkeypatch.setattr(media, "_http_get", _fetch_returning(JPEG, "image/jpeg", seen))
    fake.queue(
        "GET",
        "M1",
        {"id": "M1", "media_type": "IMAGE", "media_url": "https://scontent.xx.fbcdn.net/p.jpg"},
    )
    out = await media.view_ig_media("M1")
    assert isinstance(out, Image)
    assert out.to_image_content().mimeType == "image/jpeg"
    assert seen[0][0] == "https://scontent.xx.fbcdn.net/p.jpg"


async def test_view_ig_media_video_uses_thumbnail(fake, monkeypatch):
    seen: list = []
    monkeypatch.setattr(media, "_http_get", _fetch_returning(PNG, "image/png", seen))
    fake.queue(
        "GET",
        "V1",
        {
            "id": "V1",
            "media_type": "VIDEO",
            "media_url": "https://video.xx.fbcdn.net/v.mp4",
            "thumbnail_url": "https://scontent.xx.fbcdn.net/thumb.jpg",
        },
    )
    out = await media.view_ig_media("V1")
    assert isinstance(out, Image)
    # The video frame, not the .mp4, is fetched.
    assert seen == [("https://scontent.xx.fbcdn.net/thumb.jpg", media._MAX_VIEW_BYTES)]


async def test_view_ig_media_video_without_thumbnail_errors(fake, monkeypatch):
    async def _no_fetch(url, max_bytes):
        raise AssertionError("should not fetch when there is no thumbnail")

    monkeypatch.setattr(media, "_http_get", _no_fetch)
    fake.queue("GET", "V2", {"id": "V2", "media_type": "VIDEO", "media_url": "https://x/v.mp4"})
    out = await media.view_ig_media("V2")
    assert isinstance(out, str)
    assert "thumbnail" in json.loads(out)["error"].lower()


# ---- view_ad_creative -----------------------------------------------------


async def test_view_ad_creative(fake, monkeypatch):
    monkeypatch.setattr(media, "_http_get", _fetch_returning(PNG, "image/png"))
    fake.queue(
        "GET",
        "CR1",
        {"id": "CR1", "image_url": "https://scontent.xx.fbcdn.net/creative.png"},
    )
    out = await media.view_ad_creative("CR1")
    assert isinstance(out, Image)
    assert out.to_image_content().mimeType == "image/png"


async def test_view_ad_creative_without_image_errors(fake, monkeypatch):
    async def _no_fetch(url, max_bytes):
        raise AssertionError("should not fetch")

    monkeypatch.setattr(media, "_http_get", _no_fetch)
    fake.queue("GET", "CR2", {"id": "CR2", "object_type": "VIDEO"})
    out = await media.view_ad_creative("CR2")
    assert isinstance(out, str)
    assert json.loads(out)["error"]


# ---- save_media -----------------------------------------------------------


async def test_save_media_writes_file(monkeypatch, tmp_path):
    config.set_config(config.Config(access_token="t", media_dir=str(tmp_path)))
    try:
        monkeypatch.setattr(media, "_http_get", _fetch_returning(JPEG, "image/jpeg"))
        out = json.loads(await media.save_media("https://scontent.xx.fbcdn.net/photo.jpg"))
        assert out["bytes"] == len(JPEG)
        assert out["content_type"] == "image/jpeg"
        assert out["saved"].endswith("photo.jpg")
        assert (tmp_path / "photo.jpg").read_bytes() == JPEG
    finally:
        config._config = None


async def test_save_media_requires_media_dir(monkeypatch):
    config.set_config(config.Config(access_token="t"))  # no media_dir
    try:
        monkeypatch.setattr(media, "_http_get", _fetch_returning(JPEG, "image/jpeg"))
        out = json.loads(await media.save_media("https://scontent.xx.fbcdn.net/photo.jpg"))
        assert "FB_MEDIA_DIR" in out["error"]
    finally:
        config._config = None


async def test_save_media_filename_cannot_escape_dir(monkeypatch, tmp_path):
    config.set_config(config.Config(access_token="t", media_dir=str(tmp_path)))
    try:
        monkeypatch.setattr(media, "_http_get", _fetch_returning(PNG, "image/png"))
        out = json.loads(
            await media.save_media(
                "https://scontent.xx.fbcdn.net/x.png", filename="../../etc/evil.png"
            )
        )
        saved = out["saved"]
        # Only the basename is used, so the file stays inside FB_MEDIA_DIR.
        assert saved.endswith("evil.png")
        assert saved.startswith(str(tmp_path))
        assert (tmp_path / "evil.png").exists()
    finally:
        config._config = None


# ---- registration ---------------------------------------------------------


def test_media_tools_registered_as_reads():
    app = appmod.build_app(config.Config(access_token="t", enable_writes=False))
    names = {t.name for t in asyncio.run(app.list_tools())}
    config._config = None
    assert {"view_image", "view_ig_media", "view_ad_creative", "save_media"} <= names
