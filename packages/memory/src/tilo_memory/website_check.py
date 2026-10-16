"""The static checker for a native website's HTML (WEB-1; contracts/website.rules.md WS-02 to WS-09, ADR-0050).

`check_website(data)` is code, never a model, and stdlib only (`html.parser`, `re`). It tokenises the file, checks every
start tag, attribute, `<style>` text and `<script>` text (character references are decoded in attributes, CSS escapes
in CSS, `\\u` and `\\x` escapes in script), then scans the raw bytes on their own (WS-08), so a tokenizer that reads the
file differently from a browser still cannot let a URL through. The result is a fixed code and a line number: it never
quotes the file (a reply is model text and may echo a secret). The artifact store runs it on every `text/html`
version (AR-10); the writer's retry gets the code and line (FR-AGT-13).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser

MAX_BYTES = 524_288  # WS-02, AR-10
MAX_TAGS = 30_000  # a real page is far below; bounds html.parser's worst case
CODES = ("ws_size", "ws_encoding", "ws_element", "ws_url", "ws_css", "ws_script", "ws_raw")


@dataclass(frozen=True)
class WebsiteCheck:
    ok: bool
    code: str | None = None
    line: int | None = None


class _Refused(Exception):
    def __init__(self, code: str, line: int) -> None:
        super().__init__(code)
        self.code, self.line = code, line


_BANNED_TAGS = frozenset(
    "base link iframe frame frameset object embed applet portal fencedframe form".split()  # WS-04
    + "noscript noembed noframes xmp plaintext".split()  # raw text to a browser, markup to the tokenizer
)
_RCDATA = frozenset({"title", "textarea"})  # text to a browser: markup inside is text to a browser
_FOREIGN = frozenset({"svg", "math"})  # inside them <style> and <script> text is markup to a browser
_URL_ATTRS = frozenset(  # WS-05
    "href xlink:href src srcset imagesrcset poster background cite data codebase longdesc lowsrc dynsrc icon usemap "
    "archive profile".split()
)
_SRCSET = frozenset({"srcset", "imagesrcset"})
_NEVER_ATTRS = frozenset({"action", "formaction", "ping", "manifest"})
_DATA_URL = re.compile(
    r"data:(?:image/(?:png|jpeg|gif|webp)|font/(?:woff2?|ttf|otf)"
    r"|application/(?:font-woff2?|x-font-(?:woff|ttf|otf))|audio/[a-z0-9.+-]+|video/[a-z0-9.+-]+)[;,]",
    re.IGNORECASE,
)
_FRAGMENT = re.compile(r"#[A-Za-z0-9_-]*")
_RAW_BAD = re.compile(r"://|javascript:|vbscript:|data:text/html|<base|http-equiv|@import", re.IGNORECASE)  # WS-08
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-fA-F]{1,6})[ \t\n\r\f]?|(\r\n|[\n\r\f])|(.))", re.DOTALL)
_CSS_BAD = re.compile(r"@import|expression\s*\(|behavior|-moz-binding", re.IGNORECASE)  # WS-06
_CSS_FUNC = re.compile(r"(?<![a-z0-9_])(url|src|image-set|image|cross-fade)\s*\(", re.IGNORECASE)
_CSS_STRING = re.compile(r"\"([^\"\\]*)\"|'([^'\\]*)'")
_JS_ESCAPE = re.compile(r"\\u\{([0-9a-fA-F]{1,6})\}|\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")
_NAMES = (  # WS-07: refused as a word anywhere in script text and handlers, strings and comments included
    "fetch XMLHttpRequest WebSocket WebTransport EventSource sendBeacon RTCPeerConnection Worker SharedWorker "
    "serviceWorker importScripts eval Function postMessage opener frameElement import"
).split()
_GLOBALS = "location|navigation|history|top|parent|frames|open"
_WORD = r"(?<![\w$])(?:{})(?![\w$])"
_JS_RULES = (
    re.compile(r"://"),
    re.compile(_WORD.format("|".join(_NAMES))),
    re.compile(r"[.'\"`]\s*constructor(?![\w$])"),
    re.compile(rf"(?<![\w$.])(?:{_GLOBALS})(?![\w$])"),
    re.compile(rf"(?<![\w$])(?:window|self|globalThis|document)\s*\??\.\s*(?:{_GLOBALS})(?![\w$])"),
    re.compile(r"(?<![\w$])document\s*\??\.\s*(?:domain|cookie|write|writeln)(?![\w$])"),
    re.compile(r"(?<![\w$])(?:window|self|globalThis|document)\s*(?:\?\.)?\s*\["),
    re.compile(r"(?<![\w$])(?:setTimeout|setInterval)\s*\(\s*['\"`]"),
)
_C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_DOCTYPE = re.compile(r"[ \t\n\r\f]*<!doctype html>", re.IGNORECASE)
_BAD_COMMENT_END = re.compile(r"--!>|<!-->|<!--->")
_ESCAPED_TAG = re.compile(r"<[A-Za-z!/?]")


def _line(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _clean_url(value: str) -> str:
    return re.sub(r"[\t\n\r]", "", value).strip("".join(chr(i) for i in range(33)))


def _url_ok(value: str) -> bool:
    url = _clean_url(value)
    return url == "" or _FRAGMENT.fullmatch(url) is not None or _DATA_URL.match(url) is not None


def _srcset_urls(value: str) -> list[str]:
    """The candidate URLs of a srcset: a data URL holds commas, so split as the HTML algorithm does."""
    urls, pos, n = [], 0, len(value)
    while pos < n:
        while pos < n and value[pos] in " \t\n\f\r,":
            pos += 1
        start = pos
        while pos < n and value[pos] not in " \t\n\f\r":
            pos += 1
        if pos > start:
            urls.append(value[start:pos].rstrip(","))
        comma = value.find(",", pos)
        pos = n if comma < 0 else comma + 1
    return urls


def _unescape_css(css: str) -> str:
    def repl(m: re.Match[str]) -> str:
        if m.group(1):
            code = int(m.group(1), 16)
            return chr(code) if 0 < code <= 0x10FFFF and not 0xD800 <= code <= 0xDFFF else "\ufffd"
        return "" if m.group(2) else m.group(3)

    return _CSS_ESCAPE.sub(repl, css)


def _css_body(css: str, start: int) -> str:
    depth, i = 1, start
    while i < len(css) and depth:
        depth += {"(": 1, ")": -1}.get(css[i], 0)
        i += 1
    return css[start : i - 1] if depth == 0 else css[start:]


def css_problem(css: str) -> int | None:
    """Index of the first WS-06 violation in CSS text (after escapes), or None."""
    css = _unescape_css(css)
    bad = _CSS_BAD.search(css)
    if bad:
        return bad.start()
    for m in _CSS_FUNC.finditer(css):
        body = _css_body(css, m.end()).strip()
        if m.group(1).lower() == "url" and body[:1] not in "\"'":
            args = [body]  # an unquoted url(...) argument
        else:
            args = [a or b for a, b in _CSS_STRING.findall(body)]
            if not args and m.group(1).lower() != "url" and body[:1] not in "\"'":
                args = [""]  # image-set(), src() or image() with no string at all
        if any(_DATA_URL.match(_clean_url(a)) is None for a in args):
            return m.start()
    return None


def js_problem(script: str) -> int | None:
    """Index of the first WS-07 violation in script text or a handler, or None."""
    decoded = _JS_ESCAPE.sub(lambda m: chr(int(next(g for g in m.groups() if g), 16)), script)
    for text in (script, decoded) if decoded != script else (script,):
        for rule in _JS_RULES:
            found = rule.search(text)
            if found:
                return found.start() if text is script else 0
    return None


class _Scan(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=False)
        self.text = text
        self.tags = 0
        self.raw: str | None = None  # "script" or "style" while inside it
        self.rc: str | None = None  # "title" or "textarea" while inside it
        self.foreign = 0  # open svg or math elements
        self.buf: list[str] = []
        self.start_line = 1

    def _refuse(self, code: str, line: int | None = None) -> _Refused:
        return _Refused(code, line or self.getpos()[0])

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags += 1
        if self.tags > MAX_TAGS:
            raise self._refuse("ws_element")
        names = [name for name, _ in attrs]
        if tag in _BANNED_TAGS or self.rc:
            raise self._refuse("ws_element")
        values = {name: (value or "") for name, value in attrs}
        if tag == "meta":
            charset = set(names) == {"charset"}
            viewport = values.get("name", "").strip().lower() == "viewport" and set(names) <= {"name", "content"}
            if not (charset or viewport):
                raise self._refuse("ws_element")
        if tag == "script" and (
            "src" in values or ("type" in values and values["type"].strip().lower() != "text/javascript")
        ):
            raise self._refuse("ws_element")
        if tag in ("a", "area") and {"target", "download", "ping"} & set(names):
            raise self._refuse("ws_element")
        if "srcdoc" in values:
            raise self._refuse("ws_element")
        for name, raw in attrs:  # every occurrence: a browser uses the first of a repeated attribute, this checks all
            value = raw or ""
            if tag == "script" and name == "type" and value.strip().lower() != "text/javascript":
                raise self._refuse("ws_element")
            if name in _NEVER_ATTRS:
                raise self._refuse("ws_url")
            if name in _URL_ATTRS:
                urls = _srcset_urls(value) if name in _SRCSET else [value]
                if not all(_url_ok(url) for url in urls):
                    raise self._refuse("ws_url")
            elif name == "style" and css_problem(value) is not None:
                raise self._refuse("ws_css")
            elif name.startswith("on") and js_problem(value) is not None:
                raise self._refuse("ws_script")
        if tag in ("script", "style"):
            self.raw, self.buf, self.start_line = tag, [], self.getpos()[0]
        elif tag in _RCDATA:
            self.rc = tag
        elif tag in _FOREIGN:
            self.foreign += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):  # `<script/>` opens the element for a browser, not for the tokenizer
            raise self._refuse("ws_element")
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == self.rc:
            self.rc = None
        elif tag in _FOREIGN and self.foreign:
            self.foreign -= 1
        elif self.raw and tag == self.raw:
            body = "".join(self.buf)
            problem = css_problem(body) if tag == "style" else js_problem(body)
            if problem is None and self.foreign and "<" in body:  # markup to a browser inside svg or math
                raise _Refused("ws_element", self.start_line)
            if problem is not None:
                code = "ws_css" if tag == "style" else "ws_script"
                raise _Refused(code, self.start_line + body.count("\n", 0, problem))
            self.raw = None

    def handle_data(self, data: str) -> None:
        if self.raw:
            self.buf.append(data)
        elif _ESCAPED_TAG.search(
            data
        ):  # the tokenizer gave up on a tag: it is not a tag to a checker, maybe to a browser
            raise self._refuse("ws_element")

    def handle_comment(self, data: str) -> None:
        start = self._index()
        if self.rc or self.text.find("-->", start + 2) < 0 or _ESCAPED_TAG.search(data):
            raise self._refuse("ws_element")  # markup inside a comment may be live to a browser

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower() != "doctype html":
            raise self._refuse("ws_element")

    def handle_pi(self, data: str) -> None:
        raise self._refuse("ws_element")

    def unknown_decl(self, data: str) -> None:  # <![CDATA[ ... ]]>: a browser ends it at the first ">"
        raise self._refuse("ws_element")

    def _index(self) -> int:
        line, col = self.getpos()
        index = 0
        for _ in range(line - 1):
            index = self.text.index("\n", index) + 1
        return index + col


def check_website(data: bytes) -> WebsiteCheck:
    """WS-02 to WS-08 on the exact bytes. `ok` False carries one fixed code and the line of the first problem."""
    if type(data) is not bytes or not 1 <= len(data) <= MAX_BYTES:
        return WebsiteCheck(False, "ws_size", 1)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        return WebsiteCheck(False, "ws_encoding", data.count(b"\n", 0, error.start) + 1)
    bad = _C0.search(text)
    if text.startswith("\ufeff") or bad:
        return WebsiteCheck(False, "ws_encoding", _line(text, bad.start() if bad else 0))
    if _DOCTYPE.match(text) is None:
        return WebsiteCheck(False, "ws_encoding", 1)
    edge = _BAD_COMMENT_END.search(text)
    tail = text[text.rfind(">") + 1 :]
    if edge or _ESCAPED_TAG.search(tail):  # ends inside a tag; also keeps the tokenizer's work linear
        return WebsiteCheck(False, "ws_element", _line(text, edge.start() if edge else text.rfind(">") + 1))
    scan = _Scan(text)
    try:
        scan.feed(text)
        scan.close()
    except _Refused as refused:
        return WebsiteCheck(False, refused.code, refused.line)
    except Exception:  # noqa: BLE001 - html.parser may raise on input it cannot read; the page is not checkable
        return WebsiteCheck(False, "ws_element", scan.getpos()[0])
    if scan.raw is not None:  # ended inside <script> or <style>
        return WebsiteCheck(False, "ws_element", scan.start_line)
    for view in (text, html.unescape(text)):  # WS-08, and again with character references decoded
        found = _RAW_BAD.search(view)
        if found:
            return WebsiteCheck(False, "ws_raw", _line(view, found.start()))
    return WebsiteCheck(True)
