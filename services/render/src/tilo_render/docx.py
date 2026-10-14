"""Word OOXML reports with native charts from the existing data-bound renderer."""

import io
import zipfile
from xml.etree import ElementTree as ET

from tilo_render.pptx import render_pptx
from tilo_render.spec import BulletsBlock, ChartBlock, DeliverableSpec, ParagraphBlock, TableBlock
from tilo_render.text import lines, sanitize_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"


def _node(parent: ET.Element, ns: str, tag: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, f"{{{ns}}}{tag}", attrs)


def _paragraph(parent: ET.Element, text: str, *, bold: bool = False, bullet: bool = False) -> None:
    for line in lines(text):
        paragraph = _node(parent, W, "p")
        if bullet:
            _node(_node(paragraph, W, "r"), W, "t").text = "• "
        run = _node(paragraph, W, "r")
        if bold:
            _node(_node(run, W, "rPr"), W, "b")
        element = _node(run, W, "t")
        element.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        element.text = line


def render_docx(spec: DeliverableSpec) -> bytes:
    # Revalidate objects constructed without validation before creating any package parts.
    spec = DeliverableSpec.model_validate(spec.model_dump())
    document = ET.Element(f"{{{W}}}document")
    body = _node(document, W, "body")
    relationships = ET.Element(f"{{{P}}}Relationships")
    root_rels = ET.Element(f"{{{P}}}Relationships")
    _node(root_rels, P, "Relationship", Id="rId1", Type=R + "/officeDocument", Target="word/document.xml")
    types = ET.Element(f"{{{CT}}}Types")
    _node(
        types, CT, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml"
    )
    _node(types, CT, "Default", Extension="xml", ContentType="application/xml")
    _node(
        types,
        CT,
        "Override",
        PartName="/word/document.xml",
        ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    )
    parts: dict[str, bytes] = {}
    # Reuse the proven native chart + embedded workbook parts; their relative relationships stay intact.
    if any(isinstance(block, ChartBlock) for section in spec.sections for block in section.blocks):
        with zipfile.ZipFile(io.BytesIO(render_pptx(spec))) as deck:
            deck_types = ET.fromstring(deck.read("[Content_Types].xml"))
            for name in deck.namelist():
                if name.startswith(("ppt/charts/", "ppt/embeddings/")):
                    parts[name] = deck.read(name)
            for entry in deck_types:
                if entry.get("PartName", "").lstrip("/") in parts or entry.get("Extension") == "xlsx":
                    types.append(entry)
    _paragraph(body, spec.title, bold=True)
    if spec.subtitle:
        _paragraph(body, spec.subtitle)
    _paragraph(body, spec.date)
    chart_index = 0
    for section in spec.sections:
        _paragraph(body, section.heading, bold=True)
        for block in section.blocks:
            if isinstance(block, ParagraphBlock):
                _paragraph(body, block.text)
            elif isinstance(block, BulletsBlock):
                for item in block.bullets:
                    for line in lines(item):
                        if line.strip():
                            _paragraph(body, line, bullet=True)
            elif isinstance(block, TableBlock):
                table = next(t for t in spec.tables if t.id == block.table_id)
                node = _node(body, W, "tbl")
                for index, row in enumerate([[*table.columns], *[[str(v) for v in row] for row in table.rows]]):
                    tr = _node(node, W, "tr")
                    for value in row:
                        _paragraph(_node(tr, W, "tc"), sanitize_text(str(value)), bold=index == 0)
            elif isinstance(block, ChartBlock):
                chart_index += 1
                rid = f"rId{chart_index}"
                _node(
                    relationships,
                    P,
                    "Relationship",
                    Id=rid,
                    Type=R + "/chart",
                    Target=f"../ppt/charts/chart{chart_index}.xml",
                )
                inline = _node(_node(_node(_node(body, W, "p"), W, "r"), W, "drawing"), WP, "inline")
                _node(inline, WP, "extent", cx="5486400", cy="3200400")
                _node(inline, WP, "docPr", id=str(chart_index), name=f"Chart {chart_index}")
                graphic = _node(inline, A, "graphic")
                data = _node(graphic, A, "graphicData", uri=C)
                _node(data, C, "chart").set(f"{{{R}}}id", rid)
    section_properties = _node(body, W, "sectPr")
    _node(section_properties, W, "pgSz").set(f"{{{W}}}w", "12240")
    section_properties[0].set(f"{{{W}}}h", "15840")
    for name, root in {
        "[Content_Types].xml": types,
        "_rels/.rels": root_rels,
        "word/document.xml": document,
        "word/_rels/document.xml.rels": relationships,
    }.items():
        parts[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name, content in sorted(parts.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            package.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()
