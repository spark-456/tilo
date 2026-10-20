"""Isolated Chromium driver for BrowserWorker. Egress is gated on every request."""

from __future__ import annotations

import io
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
        if self.gate(request.url, redirect_from=redirected.url if redirected else None):
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

    def goto(self, url: str) -> dict[str, Any]:
        self._chain, self._aborted = [], None
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Error:
            if self._aborted is None:
                raise
        return self._outcome()

    def click(self, ref: str) -> dict[str, Any]:
        self._chain, self._aborted = [], None
        try:
            self.page.locator(f'[data-tilo-ref="{ref}"]').click(timeout=10000)
            self.page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Error:
            if self._aborted is None:
                raise
        return self._outcome()

    def type(self, ref: str, text: str) -> None:
        self.page.locator(f'[data-tilo-ref="{ref}"]').fill(text, timeout=10000)

    def scroll(self, direction: str) -> None:
        self.page.mouse.wheel(0, 600 if direction == "down" else -600)

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
