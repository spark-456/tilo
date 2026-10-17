"""WEB-2 / WS-11: the shell's one inline script, run in Node's `vm` against a stub window and document (no browser, no
network): it waits for exactly ONE parent message from a web origin with the right shape and size, writes the page,
then posts preview-written from its one-shot load listener."""

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
  addEventListener(type, fn, options = {}) { listeners.push({ type, fn, once: options.once === true }); },
  removeEventListener(type, fn) {
    const i = listeners.findIndex((l) => l.type === type && l.fn === fn);
    if (i >= 0) listeners.splice(i, 1);
  },
  dispatch(type) {
    for (const listener of listeners.slice()) {
      if (listener.type !== type) continue;
      listener.fn({});
      if (listener.once) this.removeEventListener(type, listener.fn);
    }
  },
};
const document = {
  open() { written.push("open"); },
  write(h) { written.push(["write", h]); },
  close() { written.push("close"); window.dispatch("load"); },
};
vm.runInNewContext(input.script, { window, document, TextEncoder });
const out = { ready: parent.posted.slice(), steps: [] };
for (const message of input.messages) {
  const event = { data: message.data, origin: message.origin, source: message.fromParent ? parent : {} };
  for (const listener of listeners.slice()) if (listener.type === "message") listener.fn(event);
  out.steps.push({
    posts: parent.posted.slice(),
    writes: written.filter((w) => Array.isArray(w)).length,
    listeners: listeners.length,
  });
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


def test_WEB_2_WS_11_the_shell_waits_for_html_instead_of_posting_preview_ready() -> None:
    assert run([])["ready"] == []


def test_WEB_2_WS_11_a_message_from_a_foreign_origin_or_another_window_is_ignored() -> None:
    steps = run([good(origin=OTHER), good(origin="null"), good(fromParent=False), good(origin="")])["steps"]
    assert all(step["writes"] == 0 and step["listeners"] == 1 and step["posts"] == [] for step in steps)


@pytest.mark.parametrize(
    "data",
    [
        None, "text", {"tilo": "other", "html": "x"}, {"tilo": "preview"}, {"tilo": "preview", "html": 5},
        {"tilo": "preview", "html": "x" * 524_289}, {"tilo": "preview", "html": "é" * 262_145},
    ],
)  # fmt: skip
def test_WEB_2_WS_11_a_message_of_the_wrong_shape_or_size_is_ignored(data: object) -> None:
    step = run([{"data": data, "origin": APP, "fromParent": True}])["steps"][0]
    assert step["writes"] == 0 and step["listeners"] == 1 and step["posts"] == []


def test_WEB_2_WS_11_the_first_good_message_is_written_once_and_the_listener_is_dropped() -> None:
    steps = run([good("<h1>one</h1>"), good("<h1>two</h1>")])["steps"]
    assert [step["writes"] for step in steps] == [1, 1]
    assert [step["listeners"] for step in steps] == [0, 0]
    assert steps[0]["posts"] == [[{"tilo": "preview-written"}, "*"]]


def test_WEB_2_WS_11_exactly_the_size_cap_is_accepted_and_a_second_web_origin_works() -> None:
    steps = run([good("x" * 524_288, origin="https://alt.example:8443")])["steps"]
    assert steps[0]["writes"] == 1 and steps[0]["listeners"] == 0
    assert steps[0]["posts"] == [[{"tilo": "preview-written"}, "*"]]
