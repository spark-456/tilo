"""Render docs/progress.md as a small local HTML dashboard (docs/progress.html, git-ignored).

Stdlib only. Handles the Markdown subset progress.md uses: headings, tables, bullet
lists, paragraphs, `code`, **bold** and [links](url). Status words in table cells get
a colour so checkpoint and reviewer states read at a glance.
"""

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "progress.md"
TARGET = ROOT / "docs" / "progress.html"

STATUS_CLASSES = [
    (re.compile(r"\b(PASS|Done|GO|Merged|MET)\b"), "ok"),
    (re.compile(r"\b(FAIL|NO-GO|Blocked|Stuck|NOT MET)\b"), "bad"),
    (re.compile(r"\b(In progress|Review|Building|Fixing|Tests)\b"), "busy"),
]

CSS = """
:root{--bg:#f7f6f2;--card:#fff;--ink:#1f1d2b;--muted:#5a5768;--line:#e3e0d8;
--ok:#1e7a4a;--ok-bg:#e3f4ea;--bad:#a3261f;--bad-bg:#fbe5e3;--busy:#7a5a00;--busy-bg:#fdf1cf}
@media (prefers-color-scheme:dark){:root{--bg:#16151c;--card:#1f1d28;--ink:#ecebf2;--muted:#a19eb2;
--line:#34313f;--ok:#7fd8a6;--ok-bg:#16352a;--bad:#f3a19b;--bad-bg:#40201e;--busy:#f1d27a;--busy-bg:#3a3017}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:19px;margin:32px 0 10px}
p,li{color:var(--ink)}.muted{color:var(--muted)}
.table{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;white-space:nowrap}tr:last-child td{border-bottom:0}
code{font:13px ui-monospace,monospace;background:var(--line);padding:1px 5px;border-radius:5px}
.ok{color:var(--ok);background:var(--ok-bg)}.bad{color:var(--bad);background:var(--bad-bg)}
.busy{color:var(--busy);background:var(--busy-bg)}a{color:inherit}
"""


def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', out)


def cell(text: str, tag: str) -> str:
    klass = next((name for pattern, name in STATUS_CLASSES if tag == "td" and pattern.search(text)), "")
    attr = f' class="{klass}"' if klass else ""
    return f"<{tag}{attr}>{inline(text.strip())}</{tag}>"


def split_row(line: str) -> list[str]:
    return [part.replace("\\|", "|") for part in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def render(markdown: str) -> str:
    blocks: list[str] = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            head, body = split_row(rows[0]), [split_row(r) for r in rows[2:]]
            thead = "".join(cell(c, "th") for c in head)
            tbody = "".join("<tr>" + "".join(cell(c, "td") for c in r) + "</tr>" for r in body)
            blocks.append(f'<div class="table"><table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>')
            continue
        if line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
            continue
        heading = re.match(r"(#{1,3}) (.*)", line)
        if heading:
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
        elif line.strip():
            blocks.append(f"<p>{inline(line)}</p>")
        i += 1
    return "\n".join(blocks)


def main() -> int:
    body = render(SOURCE.read_text(encoding="utf-8"))
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Tilo progress</title><style>{CSS}</style></head><body><main>{body}</main></body></html>"
    )
    TARGET.write_text(page, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
