"""DEMO-BROWSER: a frame is small enough to be screened, so the World's Browser panel can show it.

A run stores each masked frame as an artifact screened by the safety provider; anything it estimates over the safety
role's input cap (config/models.yaml, bytes / 3) is stored `unscreened`, and the frame route then never serves it.
Chromium on the Linux image writes a full-colour 1200x800 Wikipedia page as about 220 KB, over the cap. Frames are a
256-colour PNG of the same size: the page reads the same, masks stay black, and it is about a third of the bytes.
Real headless Chromium against a local page; skipped where no Chromium is installed.
"""

from __future__ import annotations

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.slow

_STRIPES = "".join(
    f'<div style="height:6px;background:linear-gradient(90deg,hsl({n * 7 % 360},80%,50%),hsl({n * 13 % 360},60%,70%))">'
    "</div>"
    for n in range(100)
)
PAGE = (
    "<html><body style='margin:0;font:16px sans-serif'><p>Public text before the field</p>"
    "<input type='password' style='position:absolute;left:40px;top:120px;width:200px;height:40px' value='hunter2'>"
    f"<div style='position:absolute;top:200px;width:100%'>{_STRIPES}</div></body></html>"
).encode()


class _Page(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's name
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture()
def page_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Page)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


def _cap_bytes() -> int:
    roles = yaml.safe_load((Path(__file__).resolve().parents[3] / "config" / "models.yaml").read_text())["roles"]
    return int(roles["safety"]["max_input_tokens"]) * 3  # tilo_providers.safety.estimate_safety_tokens


def test_DEMO_BROWSER_a_frame_is_a_same_size_palette_png_under_the_safety_cap_with_masks_black(page_url):
    from PIL import Image
    from tilo_browser.playwright_engine import PlaywrightDriver

    try:
        driver = PlaywrightDriver(lambda url, redirect_from=None: True, {"width": 1200, "height": 800})
    except Exception as exc:  # no Chromium in this environment
        pytest.skip(f"headless Chromium is not available: {type(exc).__name__}")
    try:
        driver.goto(page_url)
        frame = driver.screenshot(mask_refs=[])
    finally:
        driver.close()

    assert frame.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(frame) < _cap_bytes()
    with Image.open(io.BytesIO(frame)) as image:
        assert image.size == (1200, 800)  # target boxes are CSS pixels of the frame: never rescaled
        assert image.mode == "P"
        pixel = image.convert("RGB").getpixel((140, 140))  # inside the password field
    assert max(pixel) < 16, "the masked secure field stays black"
