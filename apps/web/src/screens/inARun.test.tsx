// @vitest-environment happy-dom
// CP2 #258: a bare /needs-you, /needs-you/gate or /library with a live API shows the run this
// session started last, or "No run yet"; an unknown world is "Not found" in fixture and live mode.
// Nothing is asked of the API about a world the page cannot name (no 404 or 403 on every poll).
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { HttpClient } from "../api/http";
import { forgetWorld, rememberWorld } from "../world/lastWorld";
import { useRemote } from "./remote";
import { matchScreen } from "./routes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A live API that knows only `known`: its events are empty, anything else is a 404. */
function liveApi(known: string[]) {
  const urls: string[] = [];
  const fetch = vi.fn(async (url: string | URL | Request) => {
    const path = new URL(String(url)).pathname;
    urls.push(path);
    const world = /^\/worlds\/([^/]+)/.exec(path)?.[1];
    const ok = world !== undefined && known.includes(decodeURIComponent(world));
    const body = ok ? (path.endsWith("/cards") ? [] : { events: [] }) : { detail: "Not Found" };
    return new Response(JSON.stringify(body), {
      status: ok ? 200 : 404,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof globalThis.fetch;
  return { urls, client: new HttpClient({ baseUrl: "https://api.test", fetch, pollMs: 5 }) };
}

async function visit(address: string, client: TiloClient) {
  window.history.pushState({}, "", address);
  const match = matchScreen(window.location.pathname);
  if (!match) throw new Error(`no screen at ${address}`);
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <ClientProvider client={client}>
        <match.Component params={match.params} />
      </ClientProvider>,
    );
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 30)); // a few polls
  });
  return {
    text: () => container.textContent ?? "",
    container,
    stop: () => act(async () => root.unmount()),
  };
}

beforeEach(() => forgetWorld());
afterEach(() => {
  document.body.replaceChildren();
  window.history.pushState({}, "", "/");
});

describe("CP2 #258 a bare address with a live API and no started run says so", () => {
  // Every screen that reads a run from a bare address (#264): none asks a live API about the fixture world.
  const BARE = [
    "/needs-you",
    "/needs-you/gate",
    "/needs-you/consent",
    "/meeting",
    "/library",
    "/library/artifacts",
    "/worlds",
    "/autonomy",
    "/channels",
    "/mail",
    "/team",
    "/connections",
    "/estimate",
  ];
  for (const address of BARE) {
    it(`${address}: "No run yet", and the API is not asked about any world`, async () => {
      const { client, urls } = liveApi(["w_real"]);
      const page = await visit(address, client);
      expect(page.container.querySelector('[data-testid="no-run"]')?.textContent).toContain(
        "No run yet",
      );
      expect(page.text()).not.toContain("You do not have access");
      expect(urls).toEqual([]);
      await page.stop();
    });
  }

  it("the world this session started last is shown instead, and only that world is polled", async () => {
    const { client, urls } = liveApi(["w_real"]);
    rememberWorld("w_real");
    const page = await visit("/needs-you", client);
    expect(page.container.querySelector('[data-testid="no-run"]')).toBeNull();
    expect(page.text()).toContain("Nothing needs you");
    expect(new Set(urls.map((u) => u.split("/")[2]))).toEqual(new Set(["w_real"]));
    await page.stop();
  });
});

describe("CP2 #258 an unknown world is Not found, and its events are asked for once", () => {
  it("live: /needs-you?world=bogus stops polling after the 404 and says Not found", async () => {
    const { client, urls } = liveApi(["w_real"]);
    const page = await visit("/needs-you?world=bogus", client);
    expect(page.container.querySelector('[data-testid="not-found"]')).not.toBeNull();
    expect(urls.filter((u) => u.endsWith("/events"))).toHaveLength(1);
    await page.stop();
  });

  it("live: a known world is not Not found", async () => {
    const { client } = liveApi(["w_real"]);
    const page = await visit("/needs-you?world=w_real", client);
    expect(page.container.querySelector('[data-testid="not-found"]')).toBeNull();
    await page.stop();
  });

  it("fixture: /needs-you?world=bogus is Not found, not 'Nothing needs you'", async () => {
    const page = await visit("/needs-you?world=bogus", new FixtureClient());
    expect(page.container.querySelector('[data-testid="not-found"]')).not.toBeNull();
    expect(page.text()).not.toContain("Nothing needs you");
    await page.stop();
  });

  it("fixture: a bare /needs-you still shows the fixture world, as before", async () => {
    const page = await visit("/needs-you", new FixtureClient());
    expect(page.container.querySelector('[data-testid="no-run"]')).toBeNull();
    expect(page.container.querySelector('[data-testid="not-found"]')).toBeNull();
    await page.stop();
  });
});

/** What S-05, S-06, S-07, S-10 and the selection bar do: load the layout through useRemote. The run's
 * event log (runLog.ts) is a page-lifetime subscription of its own, so it is left out here. */
function LayoutUser({ client }: { client: TiloClient }) {
  const [layout] = useRemote("load the world", (signal) => client.getLayout("w_stuck", signal));
  return <p>{layout.status}</p>;
}

describe("#264 a screen waiting on a run that has not started stops asking once it unmounts", () => {
  it("useRemote + getLayout: no request follows the unmount", async () => {
    const { client, urls } = liveApi(["w_stuck"]);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => root.render(<LayoutUser client={client} />));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 30)); // a few polls at 5 ms
    });
    expect(urls.length).toBeGreaterThan(1); // polling the stuck run's events
    await act(async () => root.unmount());
    const after = urls.length;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60)); // a dozen polls' worth
    });
    expect(urls).toHaveLength(after);
  });
});
