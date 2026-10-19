"""DOCS-OUT A4: find the workbook a person uploaded to be filled in and show its layout to the final writer.

Only this run's own upload, recorded in the world's stream, screened clean and a real .xlsx counts. The layout text is
data from the person's file (tainted, like every upload); the bytes themselves never reach a prompt.
"""

import dataclasses
from typing import Any

from tilo_harness.unit_prompt import UpstreamItem
from tilo_memory.artifacts import ArtifactStore, Scope
from tilo_render.xlsx import MAX_TEMPLATE_BYTES, describe_workbook

TEMPLATE_ID = "xlsx_template"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_RECORDS = {"artifact.created", "artifact.versioned"}


def find_template(
    artifacts: ArtifactStore, scope: Scope, stream: list[dict[str, Any]], run_id: str | None
) -> bytes | None:
    for event in stream:
        ref = event.get("data", {}).get("artifact") if event.get("type") in _RECORDS else None
        if not isinstance(ref, dict):
            continue
        version = artifacts.head(scope, ref)
        record = version.record if version is not None else {}
        if (
            record.get("origin", {}).get("kind") == "upload"
            and record.get("run_id") == run_id
            and record.get("media_type") == XLSX
            and record.get("screening") == "clean"
            and record.get("size_bytes", MAX_TEMPLATE_BYTES + 1) <= MAX_TEMPLATE_BYTES
        ):
            return artifacts.read(scope, ref)
    return None


def attach_template(
    fmt: str | None,
    artifacts: ArtifactStore,
    scope: Scope,
    stream: list[dict[str, Any]],
    run_id: str | None,
    context: Any,
) -> tuple[bytes | None, Any]:
    """The template bytes and the unit context with its layout as the first upstream item, or (None, context) when the
    deliverable is not a workbook, no usable upload exists, or the upload cannot be read (a new workbook is made)."""
    if fmt != "xlsx":
        return None, context
    data = find_template(artifacts, scope, stream, run_id)
    if data is None:
        return None, context
    try:
        layout = describe_workbook(data)
    except ValueError:
        return None, context
    item = UpstreamItem(TEMPLATE_ID, "Workbook to fill", layout, screening="clean", tainted=True)
    return data, dataclasses.replace(context, upstream=(item, *context.upstream))
