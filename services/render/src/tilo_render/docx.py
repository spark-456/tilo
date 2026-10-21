"""Word OOXML reports with real Word styles, a shaded repeating table header, a page-number footer and native charts.

The package is built by hand (no Word library): a styles part defines Title, Subtitle, Heading 1/2, List Bullet and
Table Grid, so the document reads and restyles like one written in Word. Charts reuse the existing data-bound renderer.
Deterministic: fixed part timestamps, the spec's own date, no clock, no model call. All text is untrusted and goes in
as XML text nodes only.
"""

import io
import zipfile
from xml.etree import ElementTree as ET

from tilo_render.docx_styles import NUMBERING, styles_xml
from tilo_render.pptx import render_pptx
from tilo_render.spec import BulletsBlock, ChartBlock, DeliverableSpec, Figure, FigureBlock, ParagraphBlock, TableBlock
from tilo_render.text import brand_color, lines, sanitize_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC = "http://purl.org/dc/elements/1.1/"
DCTERMS = "http://purl.org/dc/terms/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XML = "http://www.w3.org/XML/1998/namespace"
for _prefix, _ns in (
    ("w", W),
    ("r", R),
    ("c", C),
    ("a", A),
    ("wp", WP),
    ("pic", PIC),
    ("cp", CP),
    ("dc", DC),
    ("dcterms", DCTERMS),
):
    ET.register_namespace(_prefix, _ns)

_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml"
_PAGE_W, _PAGE_H, _MARGIN = 11906, 16838, 1260  # A4 in twentieths of a point
_TEXT_W = _PAGE_W - 2 * _MARGIN
_ZEBRA = "F4F6F9"


def _node(parent: ET.Element, ns: str, tag: str, **attrs: str) -> ET.Element:
    return ET.SubElement(parent, f"{{{ns}}}{tag}", {(f"{{{ns}}}{k}" if ns == W else k): v for k, v in attrs.items()})


def _run(paragraph: ET.Element, text: str, *, bold: bool = False, colour: str | None = None) -> None:
    run = _node(paragraph, W, "r")
    if bold or colour:
        props = _node(run, W, "rPr")
        if bold:
            _node(props, W, "b")
        if colour:
            _node(props, W, "color", val=colour)
    element = _node(run, W, "t")
    element.set(f"{{{XML}}}space", "preserve")
    element.text = text


def _paragraph(parent: ET.Element, text: str, *, style: str | None = None) -> None:
    """One paragraph per line of `text` (a blank line is an empty paragraph), in a named Word style."""
    for line in lines(text):
        paragraph = _node(parent, W, "p")
        if style:
            _node(_node(paragraph, W, "pPr"), W, "pStyle", val=style)
        _run(paragraph, line)


def _cell_text(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return sanitize_text(str(value))
    return f"{value:,}" if isinstance(value, int) else format(value, ",.10g")


def _table(body: ET.Element, columns: list[str], rows: list[list[object]], brand: str) -> None:
    node = _node(body, W, "tbl")
    props = _node(node, W, "tblPr")
    _node(props, W, "tblStyle", val="TableGrid")
    _node(props, W, "tblW", w="5000", type="pct")
    _node(props, W, "tblLayout", type="fixed")
    _node(
        props,
        W,
        "tblLook",
        val="04A0",
        firstRow="1",
        lastRow="0",
        firstColumn="0",
        lastColumn="0",
        noHBand="0",
        noVBand="1",
    )
    width = _TEXT_W // len(columns)
    grid = _node(node, W, "tblGrid")
    for _ in columns:
        _node(grid, W, "gridCol", w=str(width))
    numeric = [
        all(isinstance(r[i], int | float) and not isinstance(r[i], bool) for r in rows) for i in range(len(columns))
    ]
    for index, row in enumerate([[*columns], *rows]):
        tr = _node(node, W, "tr")
        trp = _node(tr, W, "trPr")
        _node(trp, W, "cantSplit")
        if index == 0:
            _node(trp, W, "tblHeader")
        for column, value in enumerate(row):
            cell = _node(tr, W, "tc")
            cell_props = _node(cell, W, "tcPr")
            _node(cell_props, W, "tcW", w=str(width), type="dxa")
            if index == 0:
                _node(cell_props, W, "shd", val="clear", color="auto", fill=brand.lstrip("#").upper())
            elif index % 2 == 0:
                _node(cell_props, W, "shd", val="clear", color="auto", fill=_ZEBRA)
            text = sanitize_text(str(value)) if index == 0 else _cell_text(value)
            for line in text.split("\n"):
                paragraph = _node(cell, W, "p")
                if numeric[column]:
                    _node(_node(paragraph, W, "pPr"), W, "jc", val="right")
                _run(paragraph, line, bold=index == 0, colour="FFFFFF" if index == 0 else None)
    _node(_node(body, W, "p"), W, "pPr")  # an empty paragraph keeps the next block off the table's border


_EMU_PER_TWIP, _EMU_PER_PX = 635, 9525
_FIGURE_MAX_H = 5_400_000  # EMU, about 15 cm: a figure never fills more than most of a page


def _figure(body: ET.Element, figure: Figure, number: int, rid: str) -> str:
    """A recorded picture as an inline drawing at the text width (never taller than _FIGURE_MAX_H); returns the media
    file's extension."""
    from PIL import Image

    with Image.open(io.BytesIO(figure.raw)) as image:
        w, h, kind = image.width, image.height, image.format
    cx = min(_TEXT_W * _EMU_PER_TWIP, w * _EMU_PER_PX)
    cy = cx * h // w
    if cy > _FIGURE_MAX_H:
        cx, cy = cx * _FIGURE_MAX_H // cy, _FIGURE_MAX_H
    paragraph = _node(body, W, "p")
    _node(_node(paragraph, W, "pPr"), W, "jc", val="center")
    inline = _node(_node(_node(paragraph, W, "r"), W, "drawing"), WP, "inline")
    _node(inline, WP, "extent", cx=str(cx), cy=str(cy))
    _node(inline, WP, "docPr", id=str(1000 + number), name=f"Figure {number}")
    data = _node(_node(inline, A, "graphic"), A, "graphicData", uri=PIC)
    picture = _node(data, PIC, "pic")
    names = _node(picture, PIC, "nvPicPr")
    _node(names, PIC, "cNvPr", id="0", name=f"figure{number}")
    _node(names, PIC, "cNvPicPr")
    fill = _node(picture, PIC, "blipFill")
    _node(fill, A, "blip").set(f"{{{R}}}embed", rid)
    _node(_node(fill, A, "stretch"), A, "fillRect")
    shape = _node(picture, PIC, "spPr")
    frame = _node(shape, A, "xfrm")
    _node(frame, A, "off", x="0", y="0")
    _node(frame, A, "ext", cx=str(cx), cy=str(cy))
    _node(_node(shape, A, "prstGeom", prst="rect"), A, "avLst")
    return "png" if kind == "PNG" else "jpeg"


def _footer(title: str) -> ET.Element:
    root = ET.Element(f"{{{W}}}ftr")
    paragraph = _node(root, W, "p")
    _node(_node(paragraph, W, "pPr"), W, "pStyle", val="Footer")
    _run(paragraph, title[:80])
    _node(_node(paragraph, W, "r"), W, "tab")
    _run(paragraph, "Page ")
    _run(_node(paragraph, W, "fldSimple", instr=" PAGE "), "1")
    return root


def _core(spec: DeliverableSpec) -> ET.Element:
    root = ET.Element(f"{{{CP}}}coreProperties")
    ET.SubElement(root, f"{{{DC}}}title").text = sanitize_text(spec.title).replace("\n", " ")[:200]
    ET.SubElement(root, f"{{{DC}}}creator").text = "Tilo"
    for tag in ("created", "modified"):
        node = ET.SubElement(root, f"{{{DCTERMS}}}{tag}", {f"{{{XSI}}}type": "dcterms:W3CDTF"})
        node.text = f"{spec.date}T00:00:00Z"
    return root


def render_docx(spec: DeliverableSpec) -> bytes:
    # Revalidate objects constructed without validation before creating any package parts.
    spec = DeliverableSpec.model_validate(spec.model_dump())
    brand = brand_color()
    document = ET.Element(f"{{{W}}}document")
    body = _node(document, W, "body")
    relationships = ET.Element(f"{{{P}}}Relationships")
    root_rels = ET.Element(f"{{{P}}}Relationships")
    _node(root_rels, P, "Relationship", Id="rId1", Type=R + "/officeDocument", Target="word/document.xml")
    _node(root_rels, P, "Relationship", Id="rId2", Type=P + "/metadata/core-properties", Target="docProps/core.xml")
    types = ET.Element(f"{{{CT}}}Types")
    _node(
        types, CT, "Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml"
    )
    _node(types, CT, "Default", Extension="xml", ContentType="application/xml")
    for part, kind in (
        ("/word/document.xml", "document.main"),
        ("/word/styles.xml", "styles"),
        ("/word/numbering.xml", "numbering"),
        ("/word/footer1.xml", "footer"),
    ):
        _node(types, CT, "Override", PartName=part, ContentType=f"{_MAIN}.{kind}+xml")
    _node(
        types,
        CT,
        "Override",
        PartName="/docProps/core.xml",
        ContentType="application/vnd.openxmlformats-package.core-properties+xml",
    )
    for rid, kind, target in (
        ("rIdStyles", "styles", "styles.xml"),
        ("rIdNumbering", "numbering", "numbering.xml"),
        ("rIdFooter", "footer", "footer1.xml"),
    ):
        _node(relationships, P, "Relationship", Id=rid, Type=f"{R}/{kind}", Target=target)
    parts: dict[str, bytes] = {"word/styles.xml": styles_xml(brand), "word/numbering.xml": NUMBERING}
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
    _paragraph(body, spec.title, style="Title")
    if spec.subtitle:
        _paragraph(body, spec.subtitle, style="Subtitle")
    _paragraph(body, spec.date, style="Subtitle")
    chart_index = 0
    figures = {f.id: f for f in spec.figures}
    figure_number = 0
    for section in spec.sections:
        _paragraph(body, section.heading, style="Heading1")
        for block in section.blocks:
            if isinstance(block, ParagraphBlock):
                _paragraph(body, block.text)
            elif isinstance(block, BulletsBlock):
                for item in block.bullets:
                    for line in lines(item):
                        if line.strip():
                            _paragraph(body, line, style="ListBullet")
            elif isinstance(block, TableBlock):
                table = next(t for t in spec.tables if t.id == block.table_id)
                _table(body, table.columns, table.rows, brand)
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
            elif isinstance(block, FigureBlock):  # a recorded picture, its caption and the page it shows
                figure, figure_number = figures[block.figure_id], figure_number + 1
                rid = f"rIdFigure{figure_number}"
                ext = _figure(body, figure, figure_number, rid)
                _node(
                    relationships,
                    P,
                    "Relationship",
                    Id=rid,
                    Type=R + "/image",
                    Target=f"media/figure{figure_number}.{ext}",
                )
                parts[f"word/media/figure{figure_number}.{ext}"] = figure.raw
                _paragraph(body, f"Figure {figure_number}: {block.caption}")
                if figure.source:
                    _paragraph(body, f"Source: {figure.source}")
    for ext in sorted({name.rsplit(".", 1)[1] for name in parts if name.startswith("word/media/")}):
        _node(types, CT, "Default", Extension=ext, ContentType=f"image/{ext}")
    section_properties = _node(body, W, "sectPr")
    _node(section_properties, W, "footerReference", type="default").set(f"{{{R}}}id", "rIdFooter")
    _node(section_properties, W, "pgSz", w=str(_PAGE_W), h=str(_PAGE_H))
    _node(
        section_properties,
        W,
        "pgMar",
        top=str(_MARGIN),
        right=str(_MARGIN),
        bottom=str(_MARGIN),
        left=str(_MARGIN),
        header="709",
        footer="709",
        gutter="0",
    )
    for name, root in {
        "[Content_Types].xml": types,
        "_rels/.rels": root_rels,
        "word/document.xml": document,
        "word/_rels/document.xml.rels": relationships,
        "word/footer1.xml": _footer(sanitize_text(spec.title).replace("\n", " ")),
        "docProps/core.xml": _core(spec),
    }.items():
        parts[name] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for name in sorted(parts, key=lambda n: (n != "[Content_Types].xml", n)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            package.writestr(info, parts[name], compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()
