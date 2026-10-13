// @vitest-environment happy-dom
// BQ-UX11-1 (docs/open-questions.md, FR-UX-11): on the live Api the Worlds nav badge and the Home and Worlds
// "needs you" counts come from the decisions the service served that are still open, never from the sample
// `needsLeft` (HR-1..HR-7, PRD 9.4). Not loaded, a failed read or an empty list shows no count at all.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup } from "../../../test-support/park/componentsHarness";
import { liveApi, mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { TiloApiError } from "../../api/http";
import type { Api } from "../api";
import type { ApiResult, DecideAck, Decision } from "../api/types";
import { usePageApp } from "../app/context";
import { HomePage } from "../pages/Home/HomePage";
import { WorldsPage } from "../pages/Worlds/WorldsPage";
import { AppShell } from "./AppShell";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const decision = (k: Decision["k"]): Decision => ({
  k,
  world: "w-live",
  title: `Card ${k}`,
  body: "Why it matters",
  yes: "Approve",
  icon: "",
  done: "",
  toast: "",
  approvedTitle: "",
});

function Page({ which }: { which: "home" | "worlds" }) {
  const app = usePageApp();
  return which === "home" ? <HomePage app={app} /> : <WorldsPage app={app} />;
}

type Reads = () => Promise<Decision[]>;

/** The live Api (every result marked live) whose decisions read is replaced. */
function withDecisions(reads: Reads) {
  const api = liveApi(fakeApi());
  api.getDecisions = async () => ({ data: await reads(), source: "live" });
  return api;
}

async function mount(which: "home" | "worlds", api: Api = fakeApi()) {
  const r = mountShell(
    <AppShell>
      <Page which={which} />
    </AppShell>,
    { api },
  );
  await settle();
  await settle();
  return r;
}

const badge = (): string | null =>
  document.querySelector(".park-shell__badge")?.textContent ?? null;
const text = (): string => document.body.textContent ?? "";
const OPEN_ONE = () => Promise.resolve([decision("depot")]);

describe("BQ_UX11_1 live: the served open decisions are the count", () => {
  it("test_BQ_UX11_1_live_nav_badge_shows_exactly_the_open_served_count", async () => {
    await mount("home", withDecisions(OPEN_ONE));
    expect(seen.store.getState().sources.live).toBe(true);
    expect(badge()).toBe("1"); // the sample count would say 2
  });

  it("test_BQ_UX11_1_live_home_count_is_the_open_served_count", async () => {
    await mount("home", withDecisions(OPEN_ONE));
    expect(text()).toContain("1 decision waiting");
    expect(text()).not.toContain("2 decisions");
    expect(text()).not.toContain("0 decisions");
  });

  it("test_BQ_UX11_1_live_worlds_count_is_the_open_served_count", async () => {
    await mount("worlds", withDecisions(OPEN_ONE));
    expect(badge()).toBe("1");
    expect(text()).not.toContain("2 decisions");
    expect(text()).not.toContain("2 buildings paused");
    expect(text()).not.toContain("0 decisions");
  });

  it("test_BQ_UX11_1_live_two_open_served_decisions_read_two", async () => {
    await mount(
      "worlds",
      withDecisions(() => Promise.resolve([decision("depot"), decision("mail")])),
    );
    expect(badge()).toBe("2");
  });
});

describe("BQ_UX11_1 live: no served decisions means no count", () => {
  const noCounts = () => {
    expect(badge()).toBeNull();
    expect(text()).not.toMatch(/\b[0-9]+ decisions?\b/);
    expect(text()).not.toMatch(/\b[0-9]+ buildings? paused\b/);
  };

  it("test_BQ_UX11_1_live_a_failed_decisions_read_shows_no_count_on_Home", async () => {
    await mount(
      "home",
      withDecisions(() => Promise.reject(new TiloApiError("down", 503, true))),
    );
    noCounts();
  });

  it("test_BQ_UX11_1_live_a_failed_decisions_read_shows_no_count_on_Worlds", async () => {
    await mount(
      "worlds",
      withDecisions(() => Promise.reject(new TiloApiError("down", 503, true))),
    );
    noCounts();
  });

  it("test_BQ_UX11_1_live_decisions_still_loading_show_no_count", async () => {
    await mount(
      "home",
      withDecisions(() => new Promise<Decision[]>(() => undefined)),
    );
    noCounts();
  });

  it("test_BQ_UX11_1_live_an_empty_served_list_shows_no_count", async () => {
    await mount(
      "home",
      withDecisions(() => Promise.resolve([])),
    );
    noCounts();
    cleanup();
    await mount(
      "worlds",
      withDecisions(() => Promise.resolve([])),
    );
    noCounts();
  });
});

describe("BQ_UX11_1 fixture path is unchanged", () => {
  it("test_BQ_UX11_1_fixture_keeps_the_sample_count_in_the_badge_and_on_Home", async () => {
    await mount("home");
    expect(seen.store.getState().sources.live).toBe(false);
    expect(badge()).toBe("2");
    expect(text()).toContain("2 decisions waiting");
  });
});

describe("BQ_UX11_1 live: an answered decision lowers the count after the server reply only", () => {
  it("test_BQ_UX11_1_live_count_drops_only_once_the_server_recorded_the_answer", async () => {
    let answer: (v: ApiResult<DecideAck>) => void = () => undefined;
    const api = withDecisions(() => Promise.resolve([decision("depot"), decision("mail")]));
    api.decide = () =>
      new Promise((resolve) => {
        answer = resolve;
      });
    await mount("worlds", api);
    expect(badge()).toBe("2");

    act(() => seen.app.decide("depot"));
    await settle();
    expect(badge()).toBe("2"); // nothing recorded yet

    await act(async () => answer({ data: { ok: true, dec: { depot: true } }, source: "live" }));
    await settle();
    expect(badge()).toBe("1");
  });

  it("test_BQ_UX11_1_live_a_rejected_answer_leaves_the_count", async () => {
    const api = withDecisions(() => Promise.resolve([decision("depot"), decision("mail")]));
    api.decide = () => Promise.reject(new TiloApiError("Tilo could not record that.", 500, true));
    await mount("worlds", api);
    act(() => seen.app.decide("depot"));
    await settle();
    expect(badge()).toBe("2");
  });
});
