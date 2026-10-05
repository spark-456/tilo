"""CH-RM, OB-01 provenance (ADR-0019, BQ-CHRM-2): tilo-channels never writes an instruction. An inbound mail is
recorded at most as a `channel.message_in` and never opens a send, and the Autopilot takes its `instruction_id` from
its caller (the owner's `world.requested`, written by tilo-api from a signed-in control). No source module names
`world.requested`, so none can build one.
"""

from __future__ import annotations

import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_channels"


def test_CH_RM_OB_01_no_channels_module_writes_a_world_requested_instruction():
    offenders = [p.name for p in sorted(SRC.glob("*.py")) if "world.requested" in p.read_text(encoding="utf-8")]
    assert offenders == []


def test_CH_RM_OB_01_no_channels_module_reads_whatsapp_or_a_message_in_as_an_instruction():
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        assert "whatsapp" not in text, path.name
        assert "channel.message_in" not in text, path.name
