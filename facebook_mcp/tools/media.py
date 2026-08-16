"""View Facebook / Instagram media inline, without downloading it by hand.

Models can't open a CDN URL or watch a video on their own, so agents end up
saving media to disk just to look at it. These tools close that gap: they fetch
the bytes from Meta's CDN and return them as inline image content the model can
see directly (``view_image`` / ``view_ig_media`` / ``view_ad_creative``), and
``save_media`` automates the download-to-disk step for files (e.g. videos) that
can't be rendered inline.

Security: media URLs can originate from untrusted content, so every fetch is
guarded against SSRF — only Meta's own CDN hosts are allowed, raw-IP hosts are
refused, redirects are re-validated per hop, and the response is size-capped and
time-bounded. ``save_media`` writes only under ``FB_MEDIA_DIR`` and uses only the
basename of a requested filename, so it can never escape that directory.
"""

from __future__ import annotations

import ipaddress
import os
import urllib.parse

import httpx
from fastmcp.utilities.types import Image

from facebook_mcp import api, config
from facebook_mcp.errors import FacebookMCPError
from facebook_mcp.tools.common import tool

# Meta's media lives on these CDNs / API hosts. A URL is allowed only when its
# host equals one of these or is a subdomain of one (matched on a dot boundary,
# so "evilfbcdn.net" does NOT match "fbcdn.net").
_ALLOWED_HOST_SUFFIXES = (
    "fbcdn.net",  # scontent-*.xx.fbcdn.net, video-*.xx.fbcdn.net, external-*
    "cdninstagram.com",  # *.cdninstagram.com
    "fbsbx.com",  # lookaside.fbsbx.com (attachments, platform lookaside)
    "facebook.com",  # graph.facebook.com, lookaside.facebook.com
    "instagram.com",  # graph.instagram.com
    "fb.com",
)

_MAX_VIEW_BYTES = 12 * 1024 * 1024  # inline images are small; cap hard
_MAX_SAVE_BYTES = 100 * 1024 * 1024  # downloads (incl. short videos) buffered in memory
_MAX_REDIRECTS = 4

_IG_VIEW_FIELDS = "id,media_type,media_product_type,media_url,thumbnail_url,permalink"
_CREATIVE_VIEW_FIELDS = "id,name,image_url,thumbnail_url,object_type"


# ---- SSRF guard -----------------------------------------------------------


def _as_ip(host: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]"))  # IPv6 URL hosts are bracketed
    except ValueError:
        return None


def _host_allowed(host: str) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_HOST_SUFFIXES)


def _check_url(url: str) -> None:
    """Raise unless ``url`` is a safe Facebook/Instagram media URL.

    Enforced before the initial request and again on every redirect hop, so a
    redirect can't bounce the fetch to an internal address.
    """
    try:
        parts = urllib.parse.urlparse(url)
    except ValueError as exc:
        raise FacebookMCPError(f"Invalid media URL: {exc}") from exc
    if parts.scheme not in ("http", "https"):
        raise FacebookMCPError(
            f"Only http(s) media URLs are allowed (got scheme {parts.scheme or 'none'!r})."
        )
    host = (parts.hostname or "").lower()
    if not host:
        raise FacebookMCPError("Media URL has no host.")
    ip = _as_ip(host)
    if ip is not None:
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise FacebookMCPError("Refusing to fetch a private / internal address.")
        raise FacebookMCPError(
            "Refusing to fetch a raw IP address; only Facebook/Instagram media hosts are allowed."
        )
    if not _host_allowed(host):
        raise FacebookMCPError(
            f"Host {host!r} is not an allowed Facebook/Instagram media host; this tool only "
            "fetches media from Meta's own CDNs."
        )


# ---- download (module-level seam: monkeypatched in tests) -----------------


async def _http_get(url: str, max_bytes: int) -> tuple[bytes, str]:
    """Fetch raw bytes and content-type, following redirects safely.

    Kept at module level so tests can monkeypatch it and stay offline. Redirects
    are followed manually so each hop is re-checked by :func:`_check_url`; the
    body is streamed and aborted past ``max_bytes``; the configured FB_TIMEOUT
    bounds the request.
    """
    timeout = float(config.current().timeout or 30)
    current_url = url
    mb = max_bytes // (1024 * 1024)
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                _check_url(current_url)
                async with client.stream("GET", current_url) as resp:
                    if resp.is_redirect:
                        loc = resp.headers.get("location")
                        if not loc:
                            raise FacebookMCPError("Redirect without a Location header.")
                        current_url = urllib.parse.urljoin(current_url, loc)
                        continue
                    if resp.status_code >= 400:
                        raise FacebookMCPError(f"Media fetch failed with HTTP {resp.status_code}.")
                    clen = resp.headers.get("content-length")
                    if clen and clen.isdigit() and int(clen) > max_bytes:
                        raise FacebookMCPError(f"Media is larger than the {mb} MB limit.")
                    ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FacebookMCPError(f"Media is larger than the {mb} MB limit.")
                        chunks.append(chunk)
                    return b"".join(chunks), ctype
    except httpx.HTTPError as exc:
        raise FacebookMCPError(f"Could not fetch media: {exc}") from exc
    raise FacebookMCPError("Too many redirects while fetching media.")


# ---- content-type helpers -------------------------------------------------


def _sniff_format(data: bytes) -> str | None:
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"GIF8":
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _image_format(ctype: str, data: bytes) -> str | None:
    """Return an image format string for ``Image(format=...)``, or None.

    Sniffs magic bytes first (a Content-Type header can lie), then falls back to
    the header's subtype.
    """
    fmt = _sniff_format(data)
    if fmt:
        return fmt
    if ctype and ctype.startswith("image/"):
        sub = ctype.split("/", 1)[1].strip().lower()
        if sub in ("jpg", "pjpeg", "x-jpeg"):
            sub = "jpeg"
        if sub and sub not in ("*", "octet-stream"):
            return sub
    return None


def _ext_for(ctype: str, url: str) -> str:
    mapping = {
        "jpeg": "jpg", "jpg": "jpg", "pjpeg": "jpg", "png": "png", "gif": "gif",
        "webp": "webp", "bmp": "bmp", "mp4": "mp4", "quicktime": "mov", "webm": "webm",
    }
    if ctype and "/" in ctype:
        sub = ctype.split("/", 1)[1].strip().lower()
        if sub in mapping:
            return mapping[sub]
    _, _, ext = urllib.parse.urlparse(url).path.rpartition(".")
    if ext and 1 <= len(ext) <= 5 and ext.isalnum():
        return ext.lower()
    return "bin"


def _url_stem(url: str) -> str:
    base = os.path.basename(urllib.parse.urlparse(url).path)
    stem = base.split(".")[0] if base else ""
    stem = "".join(c for c in stem if c.isalnum() or c in "-_")
    return stem[:64] or "media"


def _media_path(cfg: config.Config, filename: str, default_stem: str, ext: str) -> str:
    if not cfg.media_dir:
        raise FacebookMCPError(
            "Saving media needs FB_MEDIA_DIR to be configured; use view_image / view_ig_media "
            "to see images inline instead."
        )
    name = os.path.basename(filename.strip()) if filename.strip() else ""
    if not name:
        name = f"{default_stem}.{ext}"
    elif "." not in name:
        name = f"{name}.{ext}"
    base = os.path.abspath(cfg.media_dir)
    os.makedirs(base, exist_ok=True)
    path = os.path.abspath(os.path.join(base, name))
    if os.path.commonpath([base, path]) != base:  # defense-in-depth
        raise FacebookMCPError("Refusing to write outside FB_MEDIA_DIR.")
    return path


async def _fetch_image(url: str, *, context: str) -> Image:
    """Fetch a CDN URL and return it as inline image content, or raise."""
    _check_url(url)
    data, ctype = await _http_get(url, _MAX_VIEW_BYTES)
    fmt = _image_format(ctype, data)
    if not fmt:
        raise FacebookMCPError(
            f"{context} did not return a recognisable image (content-type: {ctype or 'unknown'}). "
            "For a video use view_ig_media to see its thumbnail frame, or save_media to fetch it."
        )
    return Image(data=data, format=fmt)


# ---- tools ----------------------------------------------------------------


@tool
async def view_image(url: str) -> Image:
    """View a Facebook/Instagram image inline — no manual download needed.

    Pass any media URL Meta's API gave you: an Instagram ``media_url``, a Page
    photo's ``full_picture`` / ``picture``, an ad creative's ``image_url`` /
    ``thumbnail_url``, and so on. The image is fetched from Meta's CDN and
    returned as inline image content you can look at directly. Only Facebook /
    Instagram CDN hosts are allowed, the download is size-capped, and redirects
    are re-validated (SSRF-safe).
    """
    return await _fetch_image(url, context="That URL")


@tool
async def view_ig_media(media_id: str) -> Image:
    """View an Instagram media object inline, by its id.

    Resolves the media then returns its image inline: for a photo you see the
    photo; for a video or reel you see its poster / thumbnail frame (models
    can't watch video — use save_media if you need the video file itself). Use
    get_ig_media for the caption, permalink and metrics.
    """
    obj = await api.aget(media_id, {"fields": _IG_VIEW_FIELDS})
    mtype = str(obj.get("media_type") or "").upper()
    product = str(obj.get("media_product_type") or "").upper()
    if mtype in ("VIDEO", "REELS") or product == "REELS":
        url = obj.get("thumbnail_url") or ""
        if not url:
            raise FacebookMCPError(
                "This video has no thumbnail yet (it may still be processing). Try again shortly, "
                "or use save_media to download the video file."
            )
    else:
        url = obj.get("media_url") or obj.get("thumbnail_url") or ""
        if not url:
            raise FacebookMCPError("This media has no viewable image URL.")
    return await _fetch_image(url, context="This IG media")


@tool
async def view_ad_creative(creative_id: str) -> Image:
    """View an ad creative's image inline, by its id.

    Fetches the creative's ``image_url`` (falling back to ``thumbnail_url``) so
    you can see what the ad looks like. Use get_ad_creative for the full spec.
    """
    obj = await api.aget(creative_id, {"fields": _CREATIVE_VIEW_FIELDS})
    url = obj.get("image_url") or obj.get("thumbnail_url") or ""
    if not url:
        raise FacebookMCPError(
            "This creative has no directly viewable image (it may be a video or dynamic "
            "creative). Use get_ad_creative to inspect it."
        )
    return await _fetch_image(url, context="This creative")


@tool
async def save_media(url: str, filename: str = "") -> str:
    """Download a Facebook/Instagram media file (image OR video) to local disk.

    Saves under FB_MEDIA_DIR and returns the local path, so you don't have to
    download media by hand — useful for videos (which can't be viewed inline) or
    to re-upload media later. Only the basename of ``filename`` is used, so files
    always stay inside FB_MEDIA_DIR. Requires FB_MEDIA_DIR to be set.
    """
    cfg = config.current()
    _check_url(url)
    data, ctype = await _http_get(url, _MAX_SAVE_BYTES)
    path = _media_path(cfg, filename, _url_stem(url), _ext_for(ctype, url))
    with open(path, "wb") as handle:
        handle.write(data)
    return api.dumps({"saved": path, "bytes": len(data), "content_type": ctype or "unknown"})


READ_TOOLS = [view_image, view_ig_media, view_ad_creative, save_media]
WRITE_TOOLS: list = []
