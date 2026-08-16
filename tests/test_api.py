"""API layer: appsecret_proof, pagination, error mapping, client accessor."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from facebook_mcp import api
from facebook_mcp.errors import GraphError


def test_appsecret_proof_matches_hmac():
    proof = api.appsecret_proof("tok", "secret")
    expected = hmac.new(b"secret", b"tok", hashlib.sha256).hexdigest()
    assert proof == expected


def test_paginate_follows_cursor():
    page0 = {"data": [1, 2], "paging": {"next": "u", "cursors": {"after": "A"}}}
    page1 = {"data": [3], "paging": {}}

    def get_fn(path, params):
        if "after" not in params:
            return page0
        assert params["after"] == "A"
        return page1

    assert api._paginate(get_fn, "x", None, 100) == [1, 2, 3]


def test_paginate_respects_max_items():
    page = {"data": [1, 2, 3, 4, 5], "paging": {"next": "u", "cursors": {"after": "A"}}}
    assert api._paginate(lambda p, q: page, "x", None, 3) == [1, 2, 3]


def test_paginate_stops_when_cursor_stalls():
    # A malformed response that keeps returning the same cursor must not loop.
    page = {"data": [1], "paging": {"next": "u", "cursors": {"after": "A"}}}
    assert api._paginate(lambda p, q: page, "x", None, 100) == [1, 1]


def test_map_sdk_error_extracts_fields():
    class FakeErr(Exception):
        def api_error_message(self):
            return "bad token"

        def api_error_code(self):
            return 190

        def api_error_subcode(self):
            return 460

        def api_error_type(self):
            return "OAuthException"

        def http_status(self):
            return 400

        def body(self):
            return {"error": {"fbtrace_id": "TRACE"}}

    err = api._map_sdk_error(FakeErr())
    assert isinstance(err, GraphError)
    data = err.as_dict()
    assert data["error"] == "bad token"
    assert data["code"] == 190
    assert data["subcode"] == 460
    assert data["status"] == 400
    assert data["fbtrace_id"] == "TRACE"


def test_map_sdk_error_plain_exception():
    err = api._map_sdk_error(ValueError("boom"))
    assert isinstance(err, GraphError)
    assert "boom" in str(err)


def test_current_requires_client():
    api.set_client(None)
    with pytest.raises(GraphError):
        api.current()


def test_dumps_is_readable_and_utf8():
    out = api.dumps({"name": "café", "n": 1})
    assert '"n": 1' in out
    assert "café" in out
