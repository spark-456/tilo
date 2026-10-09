"""Live transcript from Meet's captions.

Pipeline: MutationObserver in the page -> raw HTML of the captions region -> parse_caption_html (pure Python,
tested against fixtures) -> CaptionMerger (partial captions -> settled utterances) -> TranscriptStore.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .selectors import CAPTION_NOISE_LINES, ICON_LIGATURE_RE

# ---------------------------------------------------------------------------------------------------------------
# In-page observer. Sends the captions region's outerHTML (throttled to 250 ms) to Python; "" when it disappears.
# ---------------------------------------------------------------------------------------------------------------
OBSERVER_JS = r"""
(() => {
  if (window.__tiloCaptionTimer) return "already";
  const SEL = '[role="region"][aria-label*="aption" i]';
  let region = null, obs = null, pending = null, last = "";
  const push = () => {
    pending = null;
    if (!region || !region.isConnected) return;
    const html = region.outerHTML;
    if (html === last) return;
    last = html;
    window.__tilo_caption(html);
  };
  const schedule = () => { if (!pending) pending = setTimeout(push, 250); };
  const attach = () => {
    const r = document.querySelector(SEL);
    if (r && r === region && r.isConnected) return;
    if (obs) obs.disconnect();
    if (region && !r && last !== "") { last = ""; window.__tilo_caption(""); }
    region = r;
    if (!region) return;
    last = "";
    obs = new MutationObserver(schedule);
    obs.observe(region, { childList: true, subtree: true, characterData: true });
    schedule();
  };
  window.__tiloCaptionTimer = setInterval(attach, 1000);
  attach();
  return "installed";
})()
"""

_BLOCK_TAGS = {
    "div",
    "p",
    "li",
    "ul",
    "ol",
    "section",
    "article",
    "header",
    "footer",
    "table",
    "tr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}
_VOID_TAGS = {"img", "br", "hr", "input", "meta", "link", "source", "wbr", "path", "circle", "rect"}
_SKIP_TAGS = {"script", "style", "svg", "img", "button"}


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: list[_Node | str] = []


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag, {k: v or "" for k, v in attrs})
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(_Node(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def _walk_text(node: _Node, out: list[str]) -> None:
    if node.tag in _SKIP_TAGS:
        return
    if node.tag == "br":
        out.append("\n")
        return
    block = node.tag in _BLOCK_TAGS
    if block:
        out.append("\n")
    for child in node.children:
        if isinstance(child, str):
            out.append(re.sub(r"\s+", " ", child))
        else:
            _walk_text(child, out)
    if block:
        out.append("\n")


def _lines(node: _Node) -> list[str]:
    """Visible text lines, mimicking innerText: block elements break lines, inline ones do not."""
    buf: list[str] = []
    _walk_text(node, buf)
    lines = [ln.strip() for ln in "".join(buf).split("\n")]
    return [ln for ln in lines if ln and not _is_noise(ln)]


def _is_noise(line: str) -> bool:
    return line.lower() in CAPTION_NOISE_LINES or bool(ICON_LIGATURE_RE.match(line))


def _find_region(node: _Node) -> _Node | None:
    if node.attrs.get("role") == "region" and "aption" in node.attrs.get("aria-label", "").lower():
        return node
    for child in node.children:
        if isinstance(child, _Node) and (found := _find_region(child)):
            return found
    return None


def _blocks(node: _Node) -> list[_Node]:
    """Find speaker blocks: the smallest elements whose text has a name line plus at least one speech line."""
    kids = [c for c in node.children if isinstance(c, _Node) and _lines(c)]
    multi = [c for c in kids if len(_lines(c)) >= 2]
    if multi:
        out: list[_Node] = []
        for c in multi:
            out.extend(_blocks(c))
        return out
    if len(kids) == 1:
        sub = _blocks(kids[0])
        if sub:
            return sub
    return [node] if len(_lines(node)) >= 2 else []


@dataclass(frozen=True)
class CaptionBlock:
    speaker: str
    text: str


def parse_caption_html(html: str) -> list[CaptionBlock]:
    """Parse a captions-region snapshot into [(speaker, text)] in on-screen order. Pure, no browser needed."""
    if not html.strip():
        return []
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    region = _find_region(builder.root) or builder.root
    out = []
    for block in _blocks(region):
        lines = _lines(block)
        if len(lines) >= 2:
            out.append(CaptionBlock(speaker=lines[0], text=" ".join(lines[1:])))
    return out


# ---------------------------------------------------------------------------------------------------------------
@dataclass
class Utterance:
    speaker: str
    text: str
    t: float  # seconds since the meeting session started
    ts: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Open:
    speaker: str
    text: str
    prefix: str
    first_seen: float
    last_change: float
    full: str = ""  # the whole block text as Meet shows it (what later snapshots must be compared to)


def _related(old: str, new: str) -> bool:
    if not old or not new:
        return False
    if new.startswith(old) or old.startswith(new):
        return True
    return SequenceMatcher(None, old, new).ratio() >= 0.6


class CaptionMerger:
    """Turns growing, self-correcting caption blocks into one finalized utterance per stretch of speech.

    An utterance settles when its text has not changed for `settle_s`, or its block left the screen.
    If a settled block later grows (same speaker keeps talking while the block is still on screen), only the new
    suffix becomes a new utterance, so nothing is duplicated.
    """

    def __init__(self, settle_s: float = 4.0, ignore_speakers: tuple[str, ...] = ("you",), recent_s: float = 90.0):
        self.settle_s = settle_s
        self.ignore = {s.strip().lower() for s in ignore_speakers if s.strip()}
        self.recent_s = recent_s
        self._open: list[_Open] = []
        self._recent: list[tuple[float, str, str]] = []  # (finalized_at, speaker, text)
        self.t0: float | None = None

    def add_ignored(self, name: str) -> None:
        if name.strip():
            self.ignore.add(name.strip().lower())

    def feed(self, blocks: list[CaptionBlock], now: float) -> list[Utterance]:
        if self.t0 is None:
            self.t0 = now
        claimed: set[int] = set()
        for block in blocks:
            if block.speaker.strip().lower() in self.ignore or not block.text.strip():
                continue
            self._apply(block, now, claimed)
        done = [o for i, o in enumerate(self._open) if i not in claimed]
        self._open = [o for i, o in enumerate(self._open) if i in claimed]
        return [self._finalize(o, now) for o in done]

    def tick(self, now: float) -> list[Utterance]:
        settled = [o for o in self._open if now - o.last_change >= self.settle_s]
        self._open = [o for o in self._open if o not in settled]
        return [self._finalize(o, now) for o in settled]

    def open_utterances(self, now: float) -> list[tuple[Utterance, float]]:
        """Not-yet-settled speech as (provisional utterance, seconds since it last changed)."""
        t0 = self.t0 or 0.0
        return [(Utterance(o.speaker, o.text, round(o.first_seen - t0, 1)), now - o.last_change) for o in self._open]

    def flush(self, now: float) -> list[Utterance]:
        done, self._open = self._open, []
        return [self._finalize(o, now) for o in done]

    # -- internals -----------------------------------------------------------------------------------------------
    def _apply(self, block: CaptionBlock, now: float, claimed: set[int]) -> None:
        best, best_score = None, 0.0
        for i, o in enumerate(self._open):
            if o.speaker != block.speaker or i in claimed:
                continue
            eff = (block.text[len(o.prefix) :] if block.text.startswith(o.prefix) else block.text).strip()
            if _related(o.text, eff):
                score = SequenceMatcher(None, o.text, eff).quick_ratio()
                if best is None or score > best_score:
                    best, best_score = i, score
        if best is not None:
            o = self._open[best]
            eff = (block.text[len(o.prefix) :] if block.text.startswith(o.prefix) else block.text).strip()
            o.full = block.text
            if eff != o.text:
                o.text, o.last_change = eff, now
            claimed.add(best)
            return
        finals = [t for _, spk, t in self._recent if spk == block.speaker]
        if any(block.text in f for f in finals):
            return  # still-visible, already-finalized block
        end = 0
        for f in finals:  # Meet keeps earlier sentences in the block: skip everything we already emitted
            i = block.text.rfind(f)
            if i >= 0:
                end = max(end, i + len(f))
        remainder = block.text[end:].strip()
        if remainder:
            self._open.append(_Open(block.speaker, remainder, block.text[:end], now, now, block.text))
            claimed.add(len(self._open) - 1)

    def _finalize(self, o: _Open, now: float) -> Utterance:
        self._recent = [r for r in self._recent if now - r[0] <= self.recent_s]
        self._recent.append((now, o.speaker, o.full or (o.prefix + o.text)))
        return Utterance(speaker=o.speaker, text=o.text, t=round(o.first_seen - (self.t0 or 0.0), 1))


class TranscriptStore:
    """Appends utterances to transcript.jsonl and keeps them in memory for the rolling window."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.items: list[Utterance] = []
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, u: Utterance) -> None:
        self.items.append(u)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(u.to_json(), ensure_ascii=False) + "\n")

    def window(self, now_t: float, minutes: float) -> list[Utterance]:
        cutoff = now_t - minutes * 60
        return [u for u in self.items if u.t >= cutoff]


class CaptionReader:
    """Attaches the observer to a Playwright page and pushes parsed snapshots to a callback."""

    def __init__(self, page: Any, on_blocks: Any, clock: Any, snapshot_dir: Path | None = None) -> None:
        self.page, self.on_blocks, self.clock, self.snapshot_dir = page, on_blocks, clock, snapshot_dir
        self._n = 0
        self._last_html = ""

    async def start(self) -> None:
        await self.page.expose_function("__tilo_caption", self._on_snapshot)
        await self.page.evaluate(OBSERVER_JS)

    def _on_snapshot(self, html: str) -> None:
        now = self.clock.now()
        if self.snapshot_dir and html and html != self._last_html and self._n < 500:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            (self.snapshot_dir / f"{self._n:04d}.html").write_text(html, encoding="utf-8")
            self._n += 1
        self._last_html = html
        self.on_blocks(parse_caption_html(html), now)
