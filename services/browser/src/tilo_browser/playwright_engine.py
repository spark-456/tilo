"""Isolated Chromium driver for BrowserWorker. Egress is gated on every request."""

from __future__ import annotations

import io
import math
from typing import Any, cast
from urllib.parse import quote_plus, urlencode

from PIL import Image
from playwright.sync_api import Error, Request, Route, sync_playwright

_TREE_SCRIPT = """() => {
  const nodes = [...document.querySelectorAll('input,textarea,select,button,a,[role]')].slice(0, 1000);
  window.__tiloNextRef ??= 0;
  return {role:'document', name:document.title || '', attrs:{}, children:nodes.map(el => {
    if (!el.dataset.tiloRef) el.dataset.tiloRef = 't' + (++window.__tiloNextRef);
    const b = el.getBoundingClientRect();
    const role = el.getAttribute('role') ||
      ({INPUT:'textbox',TEXTAREA:'textbox',BUTTON:'button',A:'link'}[el.tagName] || el.tagName.toLowerCase());
    const name = (el.getAttribute('aria-label') || el.getAttribute('placeholder') ||
      el.innerText || el.getAttribute('name') || '').trim().slice(0,120);
    return {role, name, attrs:{id:el.dataset.tiloRef, tag:el.tagName.toLowerCase(),
      dom_id:el.getAttribute('id') || '', placeholder:el.getAttribute('placeholder') || '',
      type:(el.getAttribute('type') || '').toLowerCase(), name:el.getAttribute('name') || '',
      autocomplete:el.getAttribute('autocomplete') || '', form_method:(el.form?.method || 'none').toLowerCase(),
      href:el.getAttribute('href') || '', download:el.hasAttribute('download'),
      box:{x:Math.max(0,Math.floor(b.x)),y:Math.max(0,Math.floor(b.y)),
        width:Math.max(1,Math.ceil(b.width)),height:Math.max(1,Math.ceil(b.height))}},children:[]};
  })};
}"""

# DEMO-BROWSER: the page's own search address, from its GET search form (one text or search field), else its OpenSearch
# description, fetched inside the page so the egress gate sees the request. Page markup only, never the task's words.
_SEARCH_SCRIPT = """async () => {
  for (const form of document.querySelectorAll('form')) {
    if ((form.getAttribute('method') || 'get').toLowerCase() !== 'get') continue;
    const fields = [...form.querySelectorAll('input')].filter(
      (i) => ['search', 'text'].includes((i.getAttribute('type') || 'text').toLowerCase()) && i.name);
    if (fields.length !== 1) continue;
    const hidden = [...form.querySelectorAll('input[type="hidden"]')]
      .filter((i) => i.name && (i.value || '').length <= 40).map((i) => [i.name, i.value || '']);
    return {action: form.action, field: fields[0].name, hidden};
  }
  const link = document.querySelector('link[rel="search"][type="application/opensearchdescription+xml"]');
  if (!link || !link.href) return null;
  try {
    const xml = await (await fetch(link.href, {credentials: 'omit'})).text();
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    const url = [...doc.getElementsByTagName('Url')].find((u) => (u.getAttribute('type') || '') === 'text/html');
    const template = url ? url.getAttribute('template') || '' : '';
    return template.includes('{searchTerms}') ? {template} : null;
  } catch (e) {
    return null;
  }
}"""

# DEMO-BROWSER: where a scroll's mouse wheel goes: over the page's main content (the visible part of main, article or
# #content), else the middle of the window. The point the wheel turns at is the cursor the person sees.
_WHEEL_POINT_SCRIPT = """() => {
  const w = window.innerWidth, h = window.innerHeight;
  for (const sel of ['main', '[role="main"]', 'article', '#content', '#main']) {
    const el = document.querySelector(sel);
    if (!el) continue;
    const b = el.getBoundingClientRect();
    const left = Math.max(0, b.left), top = Math.max(0, b.top);
    const right = Math.min(w, b.right), bottom = Math.min(h, b.bottom);
    if (right - left > 40 && bottom - top > 40) return {x: (left + right) / 2, y: (top + bottom) / 2};
  }
  return {x: w / 2, y: h / 2};
}"""

ASSET_TYPES = frozenset({"image", "stylesheet", "font", "media"})  # page assets any public host may serve

_SECURE_SELECTORS = (
    'input[type="password"]',
    'input[autocomplete="one-time-code"]',
    'input[autocomplete^="cc-"]',
    'input[name*="card" i]',
    'input[name*="otp" i]',
    'input[name*="pass" i]',
    'input[id*="card" i]',
    'input[id*="otp" i]',
    'input[id*="pass" i]',
    'input[placeholder*="pass" i]',
    "iframe",
    '[contenteditable="true"]',
)


def compact_png(png: bytes) -> bytes:
    """The frame as a 256-colour PNG of the same size (masks already painted black). A page screenshot reads the same
    and is about a third of the bytes, so the run's safety screen accepts it (an estimate over the safety role's input
    cap is stored unscreened, and the World's Browser panel never gets it)."""
    with Image.open(io.BytesIO(png)) as image:
        palette = image.convert("RGB").quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    out = io.BytesIO()
    palette.save(out, "PNG", optimize=True)
    return out.getvalue()


class PlaywrightEngine:
    def __init__(self, viewport: dict[str, int] | None = None) -> None:
        self.viewport = viewport or {"width": 1200, "height": 800}

    def for_viewport(self, viewport: dict[str, int]) -> PlaywrightEngine:
        return PlaywrightEngine(viewport)

    def new_context(self, gate: Any) -> PlaywrightDriver:
        return PlaywrightDriver(gate, self.viewport)


class PlaywrightDriver:
    def __init__(self, gate: Any, viewport: dict[str, int]) -> None:
        self.gate = gate
        self.viewport = viewport
        # DEMO-BROWSER: the box the last click, typing or scroll acted on, where the mouse really was (CSS pixels in the
        # window); and a page navigation the page tried to send with a method other than GET (a posted form, refused).
        self.last_box: dict[str, int] | None = None
        self.posted: str | None = None
        self.runtime = sync_playwright().start()
        try:
            self.browser = self.runtime.chromium.launch(headless=True, args=["--no-sandbox"])
            self.context = self.browser.new_context(viewport=cast(Any, viewport), accept_downloads=False)
            self.context.route("**/*", self._route)
            self.page = self.context.new_page()
            self.page.on("request", self._hop)
        except Exception:
            self.runtime.stop()
            raise
        self._chain: list[str] = []
        self._aborted: str | None = None

    def _hop(self, request: Request) -> None:
        """Playwright calls a route handler only for the first URL of a redirect chain, so each redirect hop of the
        page's own navigation is gated here (BR-02, SEC-09); a refused hop's page is left once navigation settles."""
        redirected = request.redirected_from
        if redirected is None or not self._page_navigation(request):
            return  # a frame's page is never captured or read: iframes are masked and page text is the body's
        self._chain.append(request.url)
        if not self.gate(request.url, redirect_from=redirected.url) and self._aborted is None:
            self._aborted = request.url

    def _page_navigation(self, request: Request) -> bool:
        """A navigation of the page itself; an iframe's is a subresource here (iframes are masked, never read)."""
        try:
            return request.is_navigation_request() and request.frame == self.page.main_frame
        except Error:
            return False

    def _route(self, route: Route) -> None:
        request = route.request
        redirected = request.redirected_from
        page = self._page_navigation(request)
        if page and request.method not in ("GET", "HEAD"):
            self.posted = request.url  # BR-05: a posted form is a commit, never sent without a person
            route.abort()
            return
        # An image, stylesheet, font or media file may come from any public host (owner, 21 Oct: pages as a person sees
        # them); everything else, and every navigation, stays on the allowlist.
        asset = not page and redirected is None and request.resource_type in ASSET_TYPES
        allowed = (
            self.gate(request.url, asset=True)
            if asset
            else self.gate(request.url, redirect_from=redirected.url if redirected else None)
        )
        if allowed:
            if page:
                self._chain.append(request.url)
            route.continue_()
        else:
            if page:  # a refused iframe (e.g. a sign-in check) is blocked and counted; it does not refuse the page
                self._aborted = request.url
                self._chain.append(request.url)
            route.abort()

    def _outcome(self) -> dict[str, Any]:
        if self._aborted is not None and self.page.url != "about:blank":
            self.page.goto("about:blank")  # a page reached through a refused hop is never captured, read or clicked
        return {"chain": self._chain.copy(), "aborted": self._aborted, "final_url": self.page.url}

    def _box(self, raw: Any) -> dict[str, int] | None:
        """A box clipped to the window, in whole CSS pixels (browser.schema.json target_box), or None."""
        if not isinstance(raw, dict):
            return None
        width, height = self.viewport["width"], self.viewport["height"]
        left = min(max(0, math.floor(raw["x"])), width - 1)
        top = min(max(0, math.floor(raw["y"])), height - 1)
        right = min(width, max(left + 1, math.ceil(raw["x"] + raw["width"])))
        bottom = min(height, max(top + 1, math.ceil(raw["y"] + raw["height"])))
        return {"x": left, "y": top, "width": right - left, "height": bottom - top}

    def _settle(self) -> None:
        """After a click or an Enter: the new page's content has loaded (its images may still come, up to 2 s more)."""
        self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        try:
            self.page.wait_for_load_state("load", timeout=2000)
        except Error:
            pass

    def goto(self, url: str) -> dict[str, Any]:
        self._chain, self._aborted, self.posted, self.last_box = [], None, None, None
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Error:
            if self._aborted is None:
                raise
        return self._outcome()

    def click(self, ref: str) -> dict[str, Any]:
        """A real mouse click at the middle of the element, as it is on the page at that moment."""
        self._chain, self._aborted, self.posted = [], None, None
        target = self.page.locator(f'[data-tilo-ref="{ref}"]')
        try:
            target.scroll_into_view_if_needed(timeout=5000)
            self.last_box = self._box(target.bounding_box())
            target.click(timeout=10000)
            self._settle()
        except Error:
            if self._aborted is None:
                raise
        return self._outcome()

    def type(self, ref: str, text: str) -> None:
        """The mouse clicks into the field, then the keyboard types the words one by one (the page sees each key)."""
        self.posted = None
        field = self.page.locator(f'[data-tilo-ref="{ref}"]')
        field.scroll_into_view_if_needed(timeout=5000)
        self.last_box = self._box(field.bounding_box())
        field.click(timeout=10000)
        field.fill("", timeout=10000)
        self.page.keyboard.type(text, delay=20)

    def press(self, key: str) -> dict[str, Any]:
        """A key on the focused element; an Enter that starts a page load waits for the new page (each hop gated)."""
        self._chain, self._aborted, self.posted = [], None, None
        before = self.page.url
        try:
            self.page.keyboard.press(key)
            try:
                self.page.wait_for_url(lambda url: url != before, wait_until="domcontentloaded", timeout=3000)
            except Error:
                if self._aborted is not None:
                    raise
            else:
                self._settle()
        except Error:
            if self._aborted is None:
                raise
        return self._outcome()

    def scroll(self, direction: str) -> None:
        """The mouse wheel turns over the page's main content; the cursor is where it turned."""
        point = self.page.evaluate(_WHEEL_POINT_SCRIPT)
        x, y = float(point["x"]), float(point["y"])
        self.page.mouse.move(x, y)
        self.page.mouse.wheel(0, 600 if direction == "down" else -600)
        self.page.wait_for_timeout(250)  # the wheel scrolls asynchronously: the frame is taken once it has
        self.last_box = self._box({"x": x - 12, "y": y - 12, "width": 24, "height": 24})

    def find(self, selector: str) -> str:
        element = self.page.locator(selector)
        element.evaluate("el => {window.__tiloNextRef ??= 0; el.dataset.tiloRef ??= 't' + (++window.__tiloNextRef)}")
        return element.get_attribute("data-tilo-ref") or ""

    def read_accessibility_tree(self) -> dict:
        return self.page.evaluate(_TREE_SCRIPT)

    def page_text(self) -> str:
        return self.page.locator("body").inner_text(timeout=5000)[:20000]

    def page_title(self) -> str:
        return self.page.title()

    def search_address(self) -> str | None:
        """This site's search address with a `{words}` slot, or None (DEMO-BROWSER)."""
        try:
            found = self.page.evaluate(_SEARCH_SCRIPT)
        except Error:
            return None
        if not isinstance(found, dict):
            return None
        if isinstance(found.get("template"), str):
            return str(found["template"]).replace("{searchTerms}", "{words}", 1)
        action, field = found.get("action"), found.get("field")
        if not isinstance(action, str) or not isinstance(field, str):
            return None
        hidden = urlencode([(str(k), str(v)) for k, v in found.get("hidden") or []])
        base = action.split("#", 1)[0].split("?", 1)[0]
        return f"{base}?{hidden + '&' if hidden else ''}{quote_plus(field)}={{words}}"

    def screenshot(self, mask_refs: list[str]) -> bytes:
        selectors = [*_SECURE_SELECTORS, *(f'[data-tilo-ref="{ref}"]' for ref in mask_refs)]
        masks = [self.page.locator(selector) for selector in selectors]
        return compact_png(self.page.screenshot(type="png", mask=masks, mask_color="#000000"))

    def screenshot_meta(self) -> dict:
        return {}

    def upload(self, ref: str, path: str) -> None:
        raise RuntimeError("browser uploads are disabled")

    def download(self, ref: str) -> bytes:
        raise RuntimeError("browser downloads are disabled")

    def close(self) -> None:
        self.context.close()
        self.browser.close()
        self.runtime.stop()
