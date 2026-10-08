"""Project knowledge the assistant can answer from, gathered from several routes:

- files: everything in `context/` (and any --context file/folder): .md, .txt, .csv, .json
- URLs: --context https://... or CONTEXT_URLS (fetched once at start, text only, size-capped)
- chat: text people paste into the Meet chat during the meeting
- the agenda and the running meeting state (added by the brain, not stored here)

Retrieval is plain keyword scoring: fast, offline, no extra API. Everything here is DATA for the model, never
instructions; the prompt says so.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger("bot.knowledge")

TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".rst"}
MAX_FILE_CHARS = 60_000
MAX_URL_BYTES = 300_000
CHUNK_CHARS = 700
MAX_CHAT_ITEMS = 40
_STOP = set(
    "the a an and or but for with what which who whom whose when where why how is are was were be been do does did "
    "have has had this that these those of to in on at by from about our your their we you they it its can could "
    "should would will shall may might any some there here so far please tell me us".split()
)


@dataclass
class Source:
    name: str
    kind: str  # file | url | chat | text
    text: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1
        elif tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    text = "".join(p.parts)
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _public_host(url: str) -> bool:
    """Refuse loopback/private/link-local targets so a URL setting cannot be used to probe the local network."""
    host = urlparse(url).hostname or ""
    try:
        for info in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


def fetch_url_text(url: str, allow_private: bool = False) -> str:
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("only http(s) URLs are supported")
    if not allow_private and not _public_host(url):
        raise ValueError("refusing a private or unresolvable address")
    req = urllib.request.Request(url, headers={"User-Agent": "tilo-meet-bot/0.1"})
    with urllib.request.urlopen(req, timeout=8) as r:  # noqa: S310 (scheme checked above)
        ctype = r.headers.get("Content-Type", "")
        raw = r.read(MAX_URL_BYTES).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    return html_to_text(raw) if "html" in ctype else raw


def _terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in _STOP]


class KnowledgeBase:
    def __init__(self) -> None:
        self.sources: list[Source] = []

    # -- loading -------------------------------------------------------------------------------------------------
    def add_text(self, name: str, text: str, kind: str = "text") -> None:
        text = text.strip()
        if text:
            self.sources.append(Source(name, kind, text[:MAX_FILE_CHARS]))

    def add_chat(self, sender: str, text: str) -> None:
        """Text pasted into the meeting chat becomes context. Oldest chat items are dropped past a cap."""
        self.add_text(f"chat message from {sender}", text[:2000], "chat")
        chats = [s for s in self.sources if s.kind == "chat"]
        for old in chats[:-MAX_CHAT_ITEMS]:
            self.sources.remove(old)

    def add_file(self, path: Path) -> bool:
        if path.suffix.lower() not in TEXT_SUFFIXES:
            log.info("context: skipping %s (unsupported type; use .md/.txt/.csv/.json)", path.name)
            return False
        self.add_text(path.name, path.read_text(encoding="utf-8", errors="replace"), "file")
        return True

    def add_dir(self, path: Path) -> int:
        n = 0
        for p in sorted(path.rglob("*")):
            if p.is_file() and not p.name.startswith(".") and p.name.lower() != "readme.md":
                n += self.add_file(p)
        return n

    def add_url(self, url: str, allow_private: bool = False) -> bool:
        try:
            self.add_text(url, fetch_url_text(url, allow_private), "url")
            return True
        except Exception as e:  # network trouble must never stop the bot
            log.warning("context: could not load %s (%s)", url, e)
            return False

    def add_route(self, route: str, base: Path) -> None:
        """A --context value: URL, folder or file."""
        if route.startswith(("http://", "https://")):
            self.add_url(route)
            return
        p = Path(route)
        p = p if p.is_absolute() else base / p
        if p.is_dir():
            self.add_dir(p)
        elif p.is_file():
            self.add_file(p)
        else:
            log.warning("context: %s not found", route)

    # -- retrieval -----------------------------------------------------------------------------------------------
    def _chunks(self) -> list[tuple[Source, str]]:
        out = []
        for s in self.sources:
            buf = ""
            for para in re.split(r"\n\s*\n", s.text):
                para = para.strip()
                if not para:
                    continue
                if buf and len(buf) + len(para) > CHUNK_CHARS:
                    out.append((s, buf))
                    buf = ""
                buf = (buf + "\n" + para).strip()
                while len(buf) > CHUNK_CHARS * 2:  # very long paragraph
                    out.append((s, buf[: CHUNK_CHARS * 2]))
                    buf = buf[CHUNK_CHARS * 2 :]
            if buf:
                out.append((s, buf))
        return out

    def retrieve(self, question: str, limit_chars: int = 4500, top: int = 6) -> list[dict[str, str]]:
        """Best-matching passages for a question, as [{source, text}] within a size budget."""
        chunks = self._chunks()
        if not chunks:
            return []
        q = set(_terms(question))
        df: dict[str, int] = {}
        for _, c in chunks:
            for w in set(_terms(c)):
                df[w] = df.get(w, 0) + 1
        scored = []
        for i, (s, c) in enumerate(chunks):
            words = set(_terms(c + " " + s.name))
            score = sum(1.0 / (1 + df.get(w, 0)) + 0.3 for w in q & words)
            if s.kind == "chat":
                score *= 1.2  # something pasted live is probably relevant
            scored.append((score, i if s.kind == "chat" else -i, s, c))  # ties: newest chat, oldest doc
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        picked = [x for x in scored if x[0] > 0][:top]
        if not picked:  # broad question ("what is this project about?"): the start of each source
            seen, picked = set(), []
            for score, i, s, c in sorted(scored, key=lambda x: x[1], reverse=True):
                if s.name not in seen:
                    seen.add(s.name)
                    picked.append((score, i, s, c))
        out, used = [], 0
        for _, _, s, c in picked:
            if used + len(c) > limit_chars:
                break
            out.append({"source": s.name, "text": c})
            used += len(c)
        return out

    def describe(self) -> str:
        by = {}
        for s in self.sources:
            by[s.kind] = by.get(s.kind, 0) + 1
        return ", ".join(f"{n} {k}" for k, n in by.items()) or "nothing loaded"
