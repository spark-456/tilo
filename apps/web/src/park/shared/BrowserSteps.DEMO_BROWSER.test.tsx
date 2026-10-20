// @vitest-environment happy-dom
// DEMO-BROWSER: a run that used Tilo's browser lists what it did in its result (opened X, searched Y, read Z), in the
// recorded order and from recorded browser.* events only (HR-1). Scrolls are not steps; a refused or gated action is not
// something the browser did.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { BrowserSteps, browserSteps } from "./BrowserSteps";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let seq = 0;
const ev = (type: string, data: object) => ({ seq: ++seq, type, data, summary: "" });
const started = (session: string, host: string) => ev("browser.started", { session, host });
const acted = (session: string, kind: string, host: string, caption: string, verdict = "done") =>
  ev("browser.acted", { session, kind, host, caption, verdict });

describe("DEMO_BROWSER the result lists the browser's steps", () => {
  it("DEMO_BROWSER three page reads are read, searched, read", () => {
    const events = [
      started("bs_1", "wikipedia.org"),
      acted("bs_1", "scroll", "www.wikipedia.org", "Scrolling down"),
      acted("bs_1", "extract", "www.wikipedia.org", "Reading wikipedia.org"),
      ev("browser.stopped", { session: "bs_1", outcome: "done" }),
      started("bs_2", "www.wikipedia.org"),
      acted("bs_2", "extract", "en.wikipedia.org", "Searching www.wikipedia.org"),
      started("bs_3", "en.wikipedia.org"),
      acted("bs_3", "extract", "en.wikipedia.org", "Reading en.wikipedia.org"),
    ];
    expect(browserSteps(events)).toEqual([
      "Read www.wikipedia.org",
      "Searched en.wikipedia.org",
      "Read en.wikipedia.org",
    ]);
  });

  it("DEMO_BROWSER a taught step's actions read as what was done, refused and gated actions left out", () => {
    const events = [
      started("bs_4", "en.wikipedia.org"),
      acted("bs_4", "navigate", "en.wikipedia.org", "Searching en.wikipedia.org"),
      acted("bs_4", "click", "en.wikipedia.org", "Clicking Ada Lovelace"),
      acted("bs_4", "click", "en.wikipedia.org", "Browser action stopped", "refused"),
      acted("bs_4", "type", "en.wikipedia.org", "Waiting for you", "gated"),
      acted("bs_4", "extract", "en.wikipedia.org", "Reading page"),
    ];
    expect(browserSteps(events)).toEqual([
      "Searched en.wikipedia.org",
      "Clicked Ada Lovelace",
      "Read en.wikipedia.org",
    ]);
  });

  it("DEMO_BROWSER renders a short numbered list, and nothing for a run that never used the browser", async () => {
    const node = document.createElement("div");
    const root = createRoot(node);
    await act(async () =>
      root.render(
        <BrowserSteps
          events={[
            started("bs_5", "example.org"),
            acted("bs_5", "extract", "example.org", "Reading example.org"),
          ]}
        />,
      ),
    );
    expect(node.querySelector("ol")?.textContent).toBe("Read example.org");
    expect(node.textContent).toContain("What Tilo's browser did");
    await act(async () => root.render(<BrowserSteps events={[ev("world.started", {})]} />));
    expect(node.innerHTML).toBe("");
    await act(async () => root.unmount());
  });
});
