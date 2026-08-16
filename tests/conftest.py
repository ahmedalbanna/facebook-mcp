"""Shared test fixtures: an injected fake client (no SDK, no network) and configs."""

from __future__ import annotations

import pytest

from facebook_mcp import api, config


class FakeClient:
    """Records calls and returns queued (or empty) responses. Duck-types GraphClient."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self._responses: dict[tuple[str, str], list] = {}

    def queue(self, method: str, path: str, *responses) -> None:
        self._responses.setdefault((method.upper(), path), []).extend(responses)

    def _resolve(self, method: str, path: str):
        q = self._responses.get((method.upper(), path))
        if q:
            return q.pop(0) if len(q) > 1 else q[0]
        return {"data": []}

    def call(self, method: str, path: str, params: dict | None = None):
        self.calls.append((method.upper(), path, dict(params or {})))
        return self._resolve(method, path)

    def get(self, path, params=None):
        return self.call("GET", path, params)

    def post(self, path, params=None):
        return self.call("POST", path, params)

    def delete(self, path, params=None):
        return self.call("DELETE", path, params)

    def get_all(self, path, params=None, max_items=200):
        from facebook_mcp.api import _paginate

        return _paginate(self.get, path, params, max_items)

    def last(self):
        return self.calls[-1]


def make_config(**over) -> config.Config:
    base = dict(
        access_token="tok",
        app_id="app",
        app_secret="sec",
        api_version="v26.0",
        page_id="PAGE",
        ad_account_id="act_1",
        ig_user_id="IG",
        enable_writes=True,
    )
    base.update(over)
    return config.Config(**base)


@pytest.fixture
def fake():
    client = FakeClient()
    api.set_client(client)
    yield client
    api.set_client(None)


@pytest.fixture
def cfg_writes():
    cfg = make_config(enable_writes=True)
    config.set_config(cfg)
    yield cfg
    config._config = None


@pytest.fixture
def cfg_readonly():
    cfg = make_config(enable_writes=False)
    config.set_config(cfg)
    yield cfg
    config._config = None
