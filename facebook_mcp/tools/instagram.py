"""Instagram tools via the Instagram Graph API (IG Business account on a Page).

The IG user id is the instagram_business_account linked to a Facebook Page. Run
``discover_ig_user`` to find it, then set FB_IG_USER_ID (or pass ig_user_id).
Publishing is the standard two step flow: create a media container, then publish
it; ``publish_ig_photo`` does both in one call for images.
"""

from __future__ import annotations

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


READ_TOOLS = [
    discover_ig_user,
    get_ig_account,
    list_ig_media,
    get_ig_media,
    list_ig_comments,
    get_ig_insights,
]
WRITE_TOOLS = [
    create_ig_media_container,
    publish_ig_media,
    publish_ig_photo,
    reply_to_ig_comment,
    delete_ig_comment,
]
