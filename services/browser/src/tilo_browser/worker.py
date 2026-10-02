"""The cloud browser worker: a HandsProvider for one run (FR-CON-07, FR-CON-08, FR-CON-13).

One worker = one run = one isolated browser context, opened through `engine.new_context(gate)`
where `gate` is the egress allowlist the driver must call before EVERY request. Everything that
leaves the worker is masked; Tilo never types into a secure field or any field of a login wall.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from tilo_providers.interfaces import HandsProvider

from tilo_browser.egress import Decision, EgressBlocked, EgressPolicy, sanitise_url
from tilo_browser.login import (
    CardContext,
    CredentialEntryRefused,
    LoginSignal,
    build_login_card,
    detect_login,
    secure_field_refs,
)
from tilo_browser.masking import mask_data, mask_text


class WorkerClosed(Exception):
    """The run has ended; the worker's browser context is gone."""


@dataclass(frozen=True)
class Capture:
    url: str
    title: str
    text: str
    screenshot: bytes
    meta: dict


class BrowserWorker(HandsProvider):
    def __init__(
        self,
        engine: Any,
        policy: EgressPolicy,
        *,
        card_sink: Callable[[dict], None] | None = None,
        card_context: CardContext | None = None,
    ) -> None:
        self._policy = policy
        self._card_sink = card_sink
        self._card_context = card_context
        self._carded_hosts: set[str] = set()
        self._login_wall = False
        self._url = ""
        self._closed = False
        self._driver = engine.new_context(self._gate)

    def _gate(self, url: str, *, redirect_from: str | None = None) -> bool:
        return self._policy.check(url, redirect_from=redirect_from).allowed

    def _alive(self) -> None:
        if self._closed:
            raise WorkerClosed("the run has ended")

    def _blocked_decision(self, aborted: str) -> Decision:
        wanted = sanitise_url(aborted)
        return next((d for d in reversed(self._policy.blocked) if d.url == wanted), self._policy.blocked[-1])

    def _raise_card(self, signal: LoginSignal, url: str) -> None:
        host = urlsplit(url).hostname or ""
        if host in self._carded_hosts or self._card_sink is None or self._card_context is None:
            return
        self._carded_hosts.add(host)
        self._card_sink(build_login_card(signal, url=url, ctx=self._card_context))

    def _land(self, result: dict[str, Any]) -> dict[str, Any]:
        """Apply the egress outcome of a navigation or click, then re-inspect the page."""
        chain: list[str] = result["chain"]
        aborted: str | None = result["aborted"]
        if aborted is not None:
            hop_signal = detect_login(chain=[aborted], tree={}, text="")
            if len(chain) < 2 or hop_signal is None:
                raise EgressBlocked(self._blocked_decision(aborted))
            # A blocked SSO hop: the site needs a login, and the card is the answer.
            self._login_wall = True
            self._raise_card(hop_signal, chain[-2])
            return {"url": sanitise_url(chain[-2]), "login_required": True, "login_kind": hop_signal.kind}
        final = result["final_url"] or self._url
        signal = detect_login(chain=chain, tree=self._driver.read_accessibility_tree(), text=self._driver.page_text())
        self._url = final
        self._login_wall = signal is not None
        if signal is not None:
            self._raise_card(signal, final)
        return {
            "url": sanitise_url(final),
            "login_required": signal is not None,
            "login_kind": signal.kind if signal else None,
        }

    def navigate(self, url: str) -> dict[str, Any]:
        self._alive()
        return self._land(self._driver.goto(url))

    def find_element(self, selector: str) -> dict[str, Any]:
        self._alive()
        return {"ref": self._driver.find(selector)}

    def click(self, ref: Any) -> dict[str, Any]:
        self._alive()
        return self._land(self._driver.click(ref))

    def type(self, ref: Any, text: str) -> None:
        self._alive()
        if self._login_wall or ref in secure_field_refs(self._driver.read_accessibility_tree()):
            raise CredentialEntryRefused("Tilo never enters credentials; use a connection or an upload instead")
        self._driver.type(ref, text)

    def _scrubbed_tree(self) -> dict:
        tree = self._driver.read_accessibility_tree()
        secure = set(secure_field_refs(tree))

        def scrub(n: dict) -> dict:
            out = {k: v for k, v in n.items() if k != "children"}
            if n.get("attrs", {}).get("id") in secure:
                out.pop("value", None)
            scrubbed: dict = mask_data(out)
            scrubbed["children"] = [scrub(c) for c in n.get("children", [])]
            return scrubbed

        return scrub(tree)

    def read_accessibility_tree(self) -> dict:
        self._alive()
        return self._scrubbed_tree()

    def screenshot(self) -> bytes:
        self._alive()
        mask_refs = secure_field_refs(self._driver.read_accessibility_tree())
        return bytes(self._driver.screenshot(mask_refs=mask_refs))

    def upload_file(self, ref: Any, path: str) -> Any:
        self._alive()
        return self._driver.upload(ref, path)

    def download_file(self, ref: Any) -> bytes:
        self._alive()
        return bytes(self._driver.download(ref))

    def capture(self) -> Capture:
        self._alive()
        return Capture(
            url=sanitise_url(self._url),
            title=mask_text(self._driver.page_title()),
            text=mask_text(self._driver.page_text()),
            screenshot=self.screenshot(),
            meta=mask_data(self._driver.screenshot_meta()),
        )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._driver.close()

    def __enter__(self) -> BrowserWorker:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
