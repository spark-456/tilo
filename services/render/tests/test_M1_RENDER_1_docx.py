"""DOCX must preserve every validated block through the authenticated door."""

import io
import posixpath
import zipfile
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
from tilo_render.app import create_app

MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SPEC = {
    "title": "Report <safe>\u0001",
    "subtitle": "Quarterly",
    "date": "2026-10-14",
    "tables": [{"id": "t", "columns": ["Region", "Sales"], "rows": [["APAC", 12]]}],
    "charts": [{"id": "c", "kind": "bar", "table_id": "t", "x": "Region", "y": "Sales", "title": "Revenue"}],
    "sections": [
        {
            "heading": "Summary",
            "blocks": [
                {"type": "paragraph", "text": "First\nSecond"},
                {"type": "bullets", "bullets": ["One", "Two"]},
                {"type": "table", "table_id": "t"},
                {"type": "chart", "chart_id": "c"},
                {"type": "chart", "chart_id": "c"},
            ],
        }
    ],
}


def test_FR_MTG_03_docx_door_preserves_text_tables_and_native_chart_data():
    app = create_app(
        audience="render",
        allowed_callers=("caller",),
        oidc_verifier=lambda *_: {
            "iss": "https://accounts.google.com",
            "aud": "render",
            "email": "caller",
            "email_verified": True,
        },
    )
    client = TestClient(app)
    assert client.post("/render", json={"format": "docx", "spec": SPEC}).status_code == 401
    response = client.post("/render", json={"format": "docx", "spec": SPEC}, headers={"Authorization": "Bearer fake"})
    assert response.status_code == 200
    assert response.headers["content-type"] == MIME
    assert 'filename="deliverable.docx"' in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as package:
        document = ET.fromstring(package.read("word/document.xml"))
        texts = list(document.itertext())
        for expected in ("Report <safe>", "Quarterly", "First", "Second", "One", "Two", "APAC", "12"):
            assert expected in texts
        assert len(document.findall(".//{*}chart")) == 2
        relationships = ET.fromstring(package.read("word/_rels/document.xml.rels"))
        for rel in relationships:
            target = posixpath.normpath(posixpath.join("word", rel.attrib["Target"]))
            chart = ET.fromstring(package.read(target))
            assert "APAC" in list(chart.itertext()) and "12.0" in list(chart.itertext())
            chart_rels = ET.fromstring(
                package.read(posixpath.dirname(target) + "/_rels/" + posixpath.basename(target) + ".rels")
            )
            for child in chart_rels:
                assert (
                    posixpath.normpath(posixpath.join(posixpath.dirname(target), child.attrib["Target"]))
                    in package.namelist()
                )
