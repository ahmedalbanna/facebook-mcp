"""Tool modules for the Facebook MCP server, grouped by API surface.

Each module exposes two lists consumed by :mod:`facebook_mcp.app`:

* ``READ_TOOLS``  — always registered.
* ``WRITE_TOOLS`` — registered only when FB_ENABLE_WRITES is set.
"""
