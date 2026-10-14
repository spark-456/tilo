"""Offline transport for the real web client -> FastAPI founding integration test."""

import json
import sys

import pytest
from _ppl11a_lib import Rig

patch = pytest.MonkeyPatch()
rig = Rig(patch)
rig.as_user("u_web_founder")
rig.unwire("founder_gate")
patch.setenv("TILO_PEOPLE_BOOTSTRAP_UID", "u_web_founder")
print(json.dumps({"ready": True}), flush=True)
try:
    for line in sys.stdin:
        request = json.loads(line)
        response = rig.client.request(
            request["method"],
            request["path"],
            content=request.get("body"),
            headers={"content-type": "application/json"},
        )
        print(json.dumps({"status": response.status_code, "body": response.text}), flush=True)
finally:
    rig.client.close()
    rig.app.dependency_overrides.clear()
    patch.undo()
