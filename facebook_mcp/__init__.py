"""Facebook / Meta MCP server.

Exposes Facebook Pages, Ads (Marketing API), Instagram and Messenger over the
Model Context Protocol, built on Meta's official ``facebook-business`` SDK.

Auth model: a long-lived access token plus App ID / App Secret today, with the
auth layer isolated in :mod:`facebook_mcp.api` so an OAuth sign-in flow can be
added later without touching the tools.
"""

__version__ = "0.1.0"
