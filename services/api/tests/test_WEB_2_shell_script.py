"""WEB-2 / WS-11: the shell's one inline script, run in Node's `vm` against a stub window and document (no browser, no
network): it posts the ready message to the parent, accepts exactly ONE message from the parent window whose origin is a
web origin and whose data has the right shape and size, hands the page text to the document, and drops the listener."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from tilo_api.preview import shell

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
APP, OTHER = "https://app.example", "https://evil.example"
HARNESS = r"""
const vm = require("vm");
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const parent = { posted: [], postMessage(m, t) { this.posted.push([m, t]); } };
const listeners = [];
const written = [];
const window = {
  parent,
  addEventListener(type, fn) { listeners.push([type, fn]); },
  removeEventListener(type, fn) {
    const i = listeners.findIndex((l) => l[0] === type && l[1] === fn);
    if (i >= 0) listeners.splice(i, 1);
  },
};
const document = {
  open() { written.push("open"); },
  write(h) { written.push(["write", h]); },
  close() { written.push("close"); },
};
vm.runInNewContext(input.script, { window, document, TextEncoder });
const out = { ready: parent.posted.slice(), steps: [] };
for (const message of input.messages) {
  const event = { data: message.data, origin: message.origin, source: message.fromParent ? parent : {} };
  for (const [type, fn] of listeners.slice()) if (type === "message") fn(event);
  out.steps.push({ writes: written.filter((w) => Array.isArray(w)).length, listeners: listeners.length });
}
console.log(JSON.stringify(out));
"""


def run(messages: list[dict]) -> dict:
    script = re.search(r"<script>(.*)</script>", shell([APP, "https://alt.example:8443"]), re.DOTALL).group(1)
    done = subprocess.run(
        [NODE, "-e", HARNESS], input=json.dumps({"script": script, "messages": messages}), capture_output=True,
        text=True, timeout=30, check=True,
    )  # fmt: skip
    return json.loads(done.stdout)


def good(html: str = "<p>x</p>", origin: str = APP, fromParent: bool = True) -> dict:
    return {"data": {"tilo": "preview", "html": html}, "origin": origin, "fromParent": fromParent}


def test_WEB_2_WS_11_the_shell_posts_ready_to_the_parent_with_star_once() -> None:
    assert run([])["ready"] == [[{"tilo": "preview-ready"}, "*"]]


def test_WEB_2_WS_11_a_message_from_a_foreign_origin_or_another_window_is_ignored() -> None:
    steps = run([good(origin=OTHER), good(origin="null"), good(fromParent=False), good(origin="")])["steps"]
    assert all(step == {"writes": 0, "listeners": 1} for step in steps)


@pytest.mark.parametrize(
    "data",
    [
        None, "text", {"tilo": "other", "html": "x"}, {"tilo": "preview"}, {"tilo": "preview", "html": 5},
        {"tilo": "preview", "html": "x" * 524_289}, {"tilo": "preview", "html": "é" * 262_145},
    ],
)  # fmt: skip
def test_WEB_2_WS_11_a_message_of_the_wrong_shape_or_size_is_ignored(data: object) -> None:
    step = run([{"data": data, "origin": APP, "fromParent": True}])["steps"][0]
    assert step == {"writes": 0, "listeners": 1}


def test_WEB_2_WS_11_the_first_good_message_is_written_once_and_the_listener_is_dropped() -> None:
    steps = run([good("<h1>one</h1>"), good("<h1>two</h1>")])["steps"]
    assert steps == [{"writes": 1, "listeners": 0}, {"writes": 1, "listeners": 0}]


def test_WEB_2_WS_11_exactly_the_size_cap_is_accepted_and_a_second_web_origin_works() -> None:
    steps = run([good("x" * 524_288, origin="https://alt.example:8443")])["steps"]
    assert steps == [{"writes": 1, "listeners": 0}]
