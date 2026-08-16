"""Automated ad rules: listing, creation, spend guardrail, deletion."""

from __future__ import annotations

import json

from facebook_mcp.tools import automation


async def test_list_auto_rules(fake, cfg_writes):
    fake.queue("GET", "act_1/adrules_library", {"data": [{"id": "R1"}]})
    out = json.loads(await automation.list_auto_rules())
    assert out["data"][0]["id"] == "R1"
    _, path, params = fake.last()
    assert path == "act_1/adrules_library"
    assert "evaluation_spec" in params["fields"]


async def test_create_pause_rule_serializes_specs(fake, cfg_writes):
    fake.queue("POST", "act_1/adrules_library", {"id": "R1"})
    ev = (
        '{"evaluation_type":"SCHEDULE","filters":[{"field":"spent",'
        '"operator":"GREATER_THAN","value":10000}]}'
    )
    out = json.loads(
        await automation.create_auto_rule("Pauser", ev, '{"execution_type":"PAUSE"}')
    )
    assert out["id"] == "R1"
    _, path, params = fake.last()
    assert path == "act_1/adrules_library"
    assert params["status"] == "ENABLED"
    assert json.loads(params["execution_spec"]) == {"execution_type": "PAUSE"}
    assert json.loads(params["evaluation_spec"])["evaluation_type"] == "SCHEDULE"


async def test_create_spend_rule_blocked_without_flag(fake, cfg_writes):
    out = json.loads(
        await automation.create_auto_rule(
            "Booster", '{"evaluation_type":"TRIGGER"}', '{"execution_type":"UNPAUSE"}'
        )
    )
    assert "FB_ADS_ALLOW_ACTIVATE" in out["error"]
    assert fake.calls == []


async def test_create_spend_rule_allowed_with_flag(fake, cfg_writes):
    cfg_writes.ads_allow_activate = True
    fake.queue("POST", "act_1/adrules_library", {"id": "R2"})
    out = json.loads(
        await automation.create_auto_rule(
            "Booster", '{"evaluation_type":"TRIGGER"}', '{"execution_type":"UNPAUSE"}'
        )
    )
    assert out["id"] == "R2"


async def test_create_rule_blocked_readonly(fake, cfg_readonly):
    out = json.loads(
        await automation.create_auto_rule("X", "{}", '{"execution_type":"PAUSE"}')
    )
    assert "disabled" in out["error"].lower()
    assert fake.calls == []


async def test_delete_auto_rule(fake, cfg_writes):
    fake.queue("DELETE", "R1", {"success": True})
    out = json.loads(await automation.delete_auto_rule("R1"))
    assert out["success"] is True
    assert fake.last()[:2] == ("DELETE", "R1")
