"""Isolated Chromium driver for BrowserWorker. Egress is gated on every request."""

from __future__ import annotations

from typing import Any, cast

from playwright.sync_api import Error, Route, sync_playwright

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
        except Exception:
            self.runtime.stop()
            raise
        self._chain: list[str] = []
        self._aborted: str | None = None

    def _route(self, route: Route) -> None:
        request = route.request
        redirected = request.redirected_from
        if self.gate(request.url, redirect_from=redirected.url if redirected else None):
            if request.is_navigation_request():
                self._chain.append(request.url)
            route.continue_()
        else:
            if request.is_navigation_request():
                self._aborted = request.url
                self._chain.append(request.url)
            route.abort()

    def _outcome(self) -> dict[str, Any]:
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

    def screenshot(self, mask_refs: list[str]) -> bytes:
        selectors = [*_SECURE_SELECTORS, *(f'[data-tilo-ref="{ref}"]' for ref in mask_refs)]
        masks = [self.page.locator(selector) for selector in selectors]
        return self.page.screenshot(type="png", mask=masks, mask_color="#000000")

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
