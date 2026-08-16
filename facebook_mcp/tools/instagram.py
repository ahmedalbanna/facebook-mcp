"""Instagram tools via the Instagram Graph API (IG Business account on a Page).

The IG user id is the instagram_business_account linked to a Facebook Page. Run
``discover_ig_user`` to find it, then set FB_IG_USER_ID (or pass ig_user_id).
Publishing is the standard two step flow: create a media container, then publish
it; ``publish_ig_photo`` does both in one call for images.
"""

from __future__ import annotations

import asyncio

from facebook_mcp import api, config, guardrails
from facebook_mcp.tools.common import need, tool

_IG_FIELDS = (
    "id,username,name,followers_count,follows_count,media_count,"
    "biography,profile_picture_url,website"
)
_MEDIA_FIELDS = (
    "id,caption,media_type,media_product_type,media_url,permalink,"
    "thumbnail_url,timestamp,like_count,comments_count"
)
_IG_COMMENT_FIELDS = "id,text,username,timestamp,like_count"

# Video/reel/story containers are processed asynchronously; we poll status_code
# before publishing. Tests set _CONTAINER_POLL_DELAY = 0 to avoid real waits.
_CONTAINER_POLL_TRIES = 8
_CONTAINER_POLL_DELAY = 3.0  # seconds between status checks


def _ig(ig_user_id: str) -> str:
    return need(ig_user_id, config.current().ig_user_id, "ig_user_id", "FB_IG_USER_ID")


# ---- reads ----------------------------------------------------------------


@tool
async def discover_ig_user(page_id: str = "") -> str:
    """Find the IG Business account id linked to a Page."""
    pid = need(page_id, config.current().page_id, "page_id", "FB_PAGE_ID")
    return api.dumps(
        await api.aget(pid, {"fields": "instagram_business_account{id,username}"})
    )


@tool
async def get_ig_account(ig_user_id: str = "") -> str:
    """Get the IG Business account profile and follower counts."""
    return api.dumps(await api.aget(_ig(ig_user_id), {"fields": _IG_FIELDS}))


@tool
async def list_ig_media(ig_user_id: str = "", limit: int = 25, after: str = "") -> str:
    """List recent media on the IG account."""
    params = {"fields": _MEDIA_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{_ig(ig_user_id)}/media", params))


@tool
async def get_ig_media(media_id: str) -> str:
    """Get a single IG media object."""
    return api.dumps(await api.aget(media_id, {"fields": _MEDIA_FIELDS}))


@tool
async def list_ig_comments(media_id: str, limit: int = 25, after: str = "") -> str:
    """List comments on an IG media object."""
    params = {"fields": _IG_COMMENT_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{media_id}/comments", params))


@tool
async def get_ig_insights(
    ig_user_id: str = "",
    metric: str = "reach,impressions,profile_views",
    period: str = "day",
) -> str:
    """Read IG account insight metrics (comma-separated) over a period."""
    return api.dumps(
        await api.aget(f"{_ig(ig_user_id)}/insights", {"metric": metric, "period": period})
    )


@tool
async def get_ig_media_insights(
    media_id: str, metric: str = "reach,impressions,saved,likes,comments,shares"
) -> str:
    """Read insight metrics for a single IG media object (post/reel/story).

    Valid metrics vary by media type, e.g. reels also support plays; stories
    support replies and exits.
    """
    return api.dumps(await api.aget(f"{media_id}/insights", {"metric": metric}))


@tool
async def get_ig_container_status(creation_id: str) -> str:
    """Check a media container's processing status (status_code: IN_PROGRESS /
    FINISHED / ERROR) before publishing it."""
    return api.dumps(await api.aget(creation_id, {"fields": "id,status_code,status"}))


# ---- writes (gated by FB_ENABLE_WRITES) -----------------------------------


@tool
async def create_ig_media_container(
    caption: str = "", image_url: str = "", video_url: str = "", ig_user_id: str = ""
) -> str:
    """Create an IG media container (step 1 of publishing). Returns a creation_id."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    if not image_url and not video_url:
        return api.dumps({"error": "Provide image_url or video_url."})
    params: dict = {}
    if caption:
        params["caption"] = caption
    if image_url:
        params["image_url"] = image_url
    if video_url:
        params["video_url"] = video_url
        params["media_type"] = "REELS"
    path = f"{_ig(ig_user_id)}/media"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def publish_ig_media(creation_id: str, ig_user_id: str = "") -> str:
    """Publish a previously created media container (step 2 of publishing)."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = {"creation_id": creation_id}
    path = f"{_ig(ig_user_id)}/media_publish"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def publish_ig_photo(image_url: str, caption: str = "", ig_user_id: str = "") -> str:
    """Publish a photo to Instagram in one call (create container, then publish)."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    igu = _ig(ig_user_id)
    container_params: dict = {"image_url": image_url}
    if caption:
        container_params["caption"] = caption
    if cfg.dry_run:
        return api.dumps(
            {
                "dry_run": True,
                "would_call": [
                    {"method": "POST", "path": f"{igu}/media", "params": container_params},
                    {
                        "method": "POST",
                        "path": f"{igu}/media_publish",
                        "params": {"creation_id": "<from step 1>"},
                    },
                ],
            }
        )
    container = await api.apost(f"{igu}/media", container_params)
    creation_id = container.get("id") if isinstance(container, dict) else None
    if not creation_id:
        return api.dumps({"error": "Container creation returned no id", "response": container})
    published = await api.apost(f"{igu}/media_publish", {"creation_id": creation_id})
    return api.dumps({"container": container, "published": published})


@tool
async def reply_to_ig_comment(comment_id: str, message: str) -> str:
    """Reply to an IG comment."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = {"message": message}
    path = f"{comment_id}/replies"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def delete_ig_comment(comment_id: str) -> str:
    """Delete an IG comment."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    preview = guardrails.maybe_dry_run(cfg, "DELETE", comment_id, {})
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.adelete(comment_id, {}))


async def _await_container(creation_id: str) -> str | None:
    """Poll a container's status_code until FINISHED/ERROR or attempts run out."""
    code = None
    for i in range(_CONTAINER_POLL_TRIES):
        info = await api.aget(creation_id, {"fields": "status_code"})
        code = info.get("status_code") if isinstance(info, dict) else None
        if code in ("FINISHED", "ERROR"):
            return code
        if i < _CONTAINER_POLL_TRIES - 1:
            await asyncio.sleep(_CONTAINER_POLL_DELAY)
    return code


async def _create_and_publish(igu: str, container_params: dict, cfg, *, poll: bool) -> dict:
    """Create a media container and publish it (polling first for async media)."""
    if cfg.dry_run:
        return {
            "dry_run": True,
            "would_call": [
                {"method": "POST", "path": f"{igu}/media", "params": container_params},
                {
                    "method": "POST",
                    "path": f"{igu}/media_publish",
                    "params": {"creation_id": "<from step 1>"},
                },
            ],
        }
    container = await api.apost(f"{igu}/media", container_params)
    creation_id = container.get("id") if isinstance(container, dict) else None
    if not creation_id:
        return {"error": "Container creation returned no id", "response": container}
    if poll:
        status = await _await_container(creation_id)
        if status == "ERROR":
            detail = await api.aget(creation_id, {"fields": "status_code,status"})
            return {
                "error": "Media processing failed",
                "creation_id": creation_id,
                "status": detail,
            }
        if status != "FINISHED":
            return {
                "pending": True,
                "creation_id": creation_id,
                "message": "Media still processing; call publish_ig_media(creation_id) once "
                "get_ig_container_status reports FINISHED.",
            }
    published = await api.apost(f"{igu}/media_publish", {"creation_id": creation_id})
    return {"container": container, "published": published}


@tool
async def publish_ig_video(video_url: str, caption: str = "", ig_user_id: str = "") -> str:
    """Publish a feed video to Instagram from a public URL (create, wait, publish).

    Meta increasingly treats feed video as Reels; prefer publish_ig_reel for reels.
    """
    cfg = config.current()
    guardrails.require_writes(cfg)
    params: dict = {"video_url": video_url, "media_type": "VIDEO"}
    if caption:
        params["caption"] = caption
    return api.dumps(await _create_and_publish(_ig(ig_user_id), params, cfg, poll=True))


@tool
async def publish_ig_reel(
    video_url: str,
    caption: str = "",
    cover_url: str = "",
    share_to_feed: bool = True,
    ig_user_id: str = "",
) -> str:
    """Publish a Reel to Instagram from a public video URL (create, wait, publish)."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params: dict = {
        "video_url": video_url,
        "media_type": "REELS",
        "share_to_feed": share_to_feed,
    }
    if caption:
        params["caption"] = caption
    if cover_url:
        params["cover_url"] = cover_url
    return api.dumps(await _create_and_publish(_ig(ig_user_id), params, cfg, poll=True))


@tool
async def publish_ig_story(
    image_url: str = "", video_url: str = "", ig_user_id: str = ""
) -> str:
    """Publish an Instagram Story from a public image or video URL."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    if bool(image_url) == bool(video_url):
        return api.dumps({"error": "Provide exactly one of image_url or video_url."})
    params: dict = {"media_type": "STORIES"}
    if image_url:
        params["image_url"] = image_url
    else:
        params["video_url"] = video_url
    # Image stories finish immediately; video stories need processing time.
    return api.dumps(
        await _create_and_publish(_ig(ig_user_id), params, cfg, poll=bool(video_url))
    )


READ_TOOLS = [
    discover_ig_user,
    get_ig_account,
    list_ig_media,
    get_ig_media,
    list_ig_comments,
    get_ig_insights,
    get_ig_media_insights,
    get_ig_container_status,
]
WRITE_TOOLS = [
    create_ig_media_container,
    publish_ig_media,
    publish_ig_photo,
    publish_ig_video,
    publish_ig_reel,
    publish_ig_story,
    reply_to_ig_comment,
    delete_ig_comment,
]
