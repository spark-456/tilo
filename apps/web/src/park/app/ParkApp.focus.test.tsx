// @vitest-environment happy-dom
// WEB-3a: after a route change focus goes to the NEW page's <h1>, also when that heading is not there yet
// at the moment of the change: a code-split page whose chunk arrives late, or a page that draws its heading
// only once its data has loaded (every real page does one or both; the Placeholder shares one loaded chunk
// and has its heading at once, which hid this). The previous page's heading is hidden by Suspense while the
// new one loads and must never be the one that is focused.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q } from "../../../test-support/park/componentsHarness";
import { ParkApp } from "./ParkApp";

const gate = vi.hoisted(() => {
  let release: () => void = () => undefined;
  const opened = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { opened, release: () => release() };
});

vi.mock("./pages", async () => {
  const { lazy, createElement: h, useEffect: effect, useState: state } = await import("react");
  const page = (id: string) => () =>
    h("div", { "data-testid": `park-page-${id}` }, h("h1", null, `Page ${id}`));
  // Its heading appears only after "data" has loaded, as a real page's does.
  const slowData = (id: string) => () => {
    const [ready, setReady] = state(false);
    effect(() => {
      gate.opened.then(() => setReady(true));
    }, []);
    return h(
      "div",
      { "data-testid": `park-page-${id}` },
      ready ? h("h1", null, `Page ${id}`) : h("p", null, "Loading"),
    );
  };
  const instant = (id: string) => lazy(() => Promise.resolve({ default: page(id) }));
  const ids = ["home", "worlds", "world", "skills", "ledger", "agenda", "profile", "connectors"];
  return {
    PAGES: {
      ...Object.fromEntries(ids.map((id) => [id, instant(id)])),
      team: lazy(() => Promise.resolve({ default: slowData("team") })),
    },
  };
});

const flush = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

describe("WEB_3a_focus: a route change to a page whose heading is not there yet", () => {
  it("WEB_3a_focus_goes_to_the_new_h1_once_it_appears", async () => {
    window.history.pushState({}, "", "/park/home");
    const m = mount(<ParkApp />);
    await flush();
    expect(q(m.container, "h1").textContent).toBe("Page home");

    await act(async () => {
      window.history.pushState({}, "", "/park/team");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await flush();
    // The new page is on screen without its heading yet: nothing is focused, least of all the old heading.
    expect(m.container.querySelector('[data-testid="park-page-team"] h1')).toBeNull();
    expect(document.activeElement?.tagName).not.toBe("H1");

    await act(async () => {
      gate.release();
      await gate.opened;
    });
    await flush();
    const heading = m.container.querySelector('[data-testid="park-page-team"] h1') as HTMLElement;
    expect(heading.textContent).toBe("Page team");
    expect(document.activeElement).toBe(heading);
  });

  it("WEB_3a_focus_is_not_stolen_when_the_person_moved_focus_meanwhile", async () => {
    window.history.pushState({}, "", "/park/home");
    const m = mount(<ParkApp />);
    await flush();
    await act(async () => {
      window.history.pushState({}, "", "/park/team");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await flush();
    const elsewhere = document.createElement("button");
    document.body.append(elsewhere);
    elsewhere.focus();
    await act(async () => {
      gate.release();
      await gate.opened;
    });
    await flush();
    expect(document.activeElement).toBe(elsewhere);
    expect(m.container.querySelector('[data-testid="park-page-team"] h1')).not.toBeNull();
    elsewhere.remove();
  });
});
