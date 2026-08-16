"""Messenger tools: read Page conversations and messages, and send messages.

Sending uses the Messenger Send API (POST /{page-id}/messages) and needs a Page
access token with pages_messaging. recipient_id is the user's page-scoped id
(PSID); replies are subject to Meta's messaging window and policy.
"""

from __future__ import annotations

import json

from facebook_mcp import api, config, guardrails
from facebook_mcp.tools.common import need, tool

_CONVERSATION_FIELDS = "id,snippet,updated_time,unread_count,message_count,participants"
_MESSAGE_FIELDS = "id,from,to,message,created_time"


def _page(page_id: str) -> str:
    return need(page_id, config.current().page_id, "page_id", "FB_PAGE_ID")


# ---- reads ----------------------------------------------------------------


@tool
async def list_conversations(page_id: str = "", limit: int = 25, after: str = "") -> str:
    """List Messenger conversations for a Page, most recently updated first."""
    params = {"fields": _CONVERSATION_FIELDS, "platform": "messenger", "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{_page(page_id)}/conversations", params))


@tool
async def list_messages(conversation_id: str, limit: int = 25, after: str = "") -> str:
    """List messages within a conversation."""
    params = {"fields": _MESSAGE_FIELDS, "limit": limit}
    if after:
        params["after"] = after
    return api.dumps(await api.aget(f"{conversation_id}/messages", params))


# ---- writes (gated by FB_ENABLE_WRITES) -----------------------------------


@tool
async def send_message(
    recipient_id: str, text: str, page_id: str = "", messaging_type: str = "RESPONSE"
) -> str:
    """Send a text message to a user (PSID) via the Messenger Send API."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    params = {
        "recipient": json.dumps({"id": recipient_id}),
        "message": json.dumps({"text": text}),
        "messaging_type": messaging_type,
    }
    path = f"{_page(page_id)}/messages"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


@tool
async def send_image(
    recipient_id: str, image_url: str, page_id: str = "", messaging_type: str = "RESPONSE"
) -> str:
    """Send an image attachment to a user (PSID) via the Messenger Send API."""
    cfg = config.current()
    guardrails.require_writes(cfg)
    attachment = {"type": "image", "payload": {"url": image_url, "is_reusable": True}}
    params = {
        "recipient": json.dumps({"id": recipient_id}),
        "message": json.dumps({"attachment": attachment}),
        "messaging_type": messaging_type,
    }
    path = f"{_page(page_id)}/messages"
    preview = guardrails.maybe_dry_run(cfg, "POST", path, params)
    if preview:
        return api.dumps(preview)
    return api.dumps(await api.apost(path, params))


READ_TOOLS = [list_conversations, list_messages]
WRITE_TOOLS = [send_message, send_image]
