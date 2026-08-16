"""Facebook Pages tools: content, posts, comments and Page insights.

Note on tokens: publishing as a Page and reading some Page edges require a
*Page* access token (or a user token carrying pages_* permissions). Run
``list_pages`` to discover the Pages you manage; set FB_ACCESS_TOKEN to the
relevant Page token (or FB_PAGE_ID for a default page) as needed.
"""

from __future__ import annotations

from facebook_mcp import api, config, guardrails
from facebook_mcp.tools.common import need, tool

_PAGE_FIELDS = "id,name,about,category,fan_count,followers_count,link,username,verification_status"
_POST_FIELDS = (
    "id,message,story,created_time,permalink_url,status_type,"
    "shares,likes.summary(true),comments.summary(true)"
)
_COMMENT_FIELDS = "id,from,message,created_time,like_count,comment_count"


def _page(page_id: str) -> str:
    return need(page_id, config.current().page_id, "page_id", "FB_PAGE_ID")


# ---- reads ----------------------------------------------------------------


@tool
async def list_pages() -> str:
    """List the Pages the token can manage (GET /me/accounts)."""
    data = await api.aget_all("me/accounts", {"fields": "id,name,category,tasks"}, max_items=100)
    return api.dumps({"data": data})


@tool
async def get_page(page_id: str = "") -> str:
    """Get a Page's profile and follower counts."""
    pid = _page(page_id)
    return api.dumps(await api.aget(pid, {"fields": _PAGE_FIELDS}))


@tool
async def list_page_posts(page_id: str = "", limit: int = 25, after: str = "") -> str:
    """List recent posts on a Page with engagement summaries."""
    pid = _page(page_id)
    params = {"fields": _POST_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{pid}/posts", params))


@tool
async def get_post(post_id: str) -> str:
    """Get a single post with engagement summaries."""
    return api.dumps(await api.aget(post_id, {"fields": _POST_FIELDS}))


@tool
async def list_post_comments(post_id: str, limit: int = 25, after: str = "") -> str:
    """List comments on a post or other commentable object."""
    params = {"fields": _COMMENT_FIELDS, "limit": limit, "order": "reverse_chronological"}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{post_id}/comments", params))


@tool
async def get_page_insights(
    page_id: str = "",
    metric: str = "page_impressions,page_engaged_users",
    period: str = "day",
) -> str:
    """Read Page insight metrics (comma-separated) over a period (day/week/days_28)."""
    pid = _page(page_id)
    return api.dumps(await api.aget(f"{pid}/insights", {"metric": metric, "period": period}))


# ---- writes (gated by FB_ENABLE_WRITES) -----------------------------------


@tool
async def create_page_post(message: str, link: str = "", page_id: str = "") -> str:
    """Publish a post to a Page's feed. Optionally attach a link."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    pid = _page(page_id)
    params = {"message": message}
    if link:
        params["link"] = link
    path = f"{pid}/feed"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def update_post(post_id: str, message: str) -> str:
    """Edit the message of an existing Page post."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = {"message": message}
    preview = guardrails.maybe_dry_run(cfg, "POST", post_id, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(post_id, params))


@tool
async def delete_post(post_id: str) -> str:
    """Delete a Page post."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    preview = guardrails.maybe_dry_run(cfg, "DELETE", post_id, {})
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.adelete(post_id, {}))


@tool
async def comment_on_object(object_id: str, message: str) -> str:
    """Add a comment to a post, photo or other commentable object."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = {"message": message}
    path = f"{object_id}/comments"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def delete_comment(comment_id: str) -> str:
    """Delete a comment."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    preview = guardrails.maybe_dry_run(cfg, "DELETE", comment_id, {})
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.adelete(comment_id, {}))


READ_TOOLS = [
    list_pages,
    get_page,
    list_page_posts,
    get_post,
    list_post_comments,
    get_page_insights,
]
WRITE_TOOLS = [
    create_page_post,
    update_post,
    delete_post,
    comment_on_object,
    delete_comment,
]
