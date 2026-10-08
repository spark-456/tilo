// @vitest-environment happy-dom
// STARTER-1 (BQ-STARTER-1): the web half of the default sample project. tilo-api lists `w_sample_village_basic`
// with `sample: true`; the pages mark it ("Sample" badge, one line saying it is a replay, not the person's work),
// Hide is this browser's (localStorage), "Show sample project" asks `?include_sample=1`, and nothing is ever
// written to the API for it. No network: a fake fetch stands in for tilo-api.
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, q } from "../../../test-support/park/componentsHarness";
import { todayRegion } from "../../../test-support/park/homeHarness";
import { liveSourced, mountLiveHome } from "../../../test-support/park/liveHomeHarness";
import {
  control,
  hasControl,
  liveWorldsApi,
  mountWorld,
  pageText,
} from "../../../test-support/park/worldHarness";
import { type WorldsApi, flush, renderWorlds } from "../../../test-support/park/worldsHarness";
import { HttpClient } from "../../api/http";
import { replayBanner } from "../../world/replay";
import { type WorldListItem, worldsFromList } from "../api/live/worldsFromList";
import { createLiveApi } from "../api/liveApi";
import {
  SAMPLE_NOTE,
  SAMPLE_WORLD_ID,
  hideSample,
  isSampleHidden,
  showSample,
  wantsSample,
} from "./sampleChoice";

const BASE = "https://api.example.test";
const TITLE = "Sample: Triage my inbox and answer the supplier about Thursday";
const sampleItem: WorldListItem = {
  world_id: SAMPLE_WORLD_ID,
  title: TITLE,
  status: "completed",
  created_at: "2026-09-29T09:30:02.000Z",
  last_seq: 44,
  sample: true,
};
const own: WorldListItem = {
  world_id: "w_mine",
  title: "Mine",
  status: "started",
  created_at: null,
  last_seq: 3,
};
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("STARTER_1 the person's choice", () => {
  it("STARTER_1_defaults_show_nothing_extra_and_hide_wins_over_show", () => {
    expect([isSampleHidden(), wantsSample()]).toEqual([false, false]);
    showSample();
    expect([isSampleHidden(), wantsSample()]).toEqual([false, true]);
    hideSample();
    expect([isSampleHidden(), wantsSample()]).toEqual([true, false]);
    showSample();
    expect([isSampleHidden(), wantsSample()]).toEqual([false, true]);
  });

  it("STARTER_1_a_storage_that_throws_still_remembers_for_this_page", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    hideSample();
    expect(isSampleHidden()).toBe(true);
    showSample();
    expect(isSampleHidden()).toBe(false);
    expect(wantsSample()).toBe(true);
  });
});

describe("STARTER_1 the live Api", () => {
  const served = (items: WorldListItem[]) => {
    const fetchSpy = vi.fn(async () => json({ worlds: items, next_cursor: null }));
    const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
    const urls = () =>
      fetchSpy.mock.calls.map((c) => String((c as unknown[])[0]).replace(BASE, ""));
    return { api, urls };
  };

  it("STARTER_1_worldsFromList_marks_only_the_sample", () => {
    const [sample, mine] = worldsFromList([sampleItem, own]);
    expect(sample?.sample).toBe(true);
    expect(sample?.name).toBe(TITLE);
    expect(mine && "sample" in mine).toBe(false);
  });

  it("STARTER_1_the_list_read_is_unchanged_until_a_person_asks_for_the_sample", async () => {
    const { api, urls } = served([sampleItem]);
    const r = await api.getWorlds({}, []);
    expect(urls()).toEqual(["/worlds?limit=100"]);
    expect(r.data.map((w) => w.id)).toEqual([SAMPLE_WORLD_ID]);
  });

  it("STARTER_1_show_asks_include_sample_and_hide_drops_it_here_only", async () => {
    const { api, urls } = served([own, sampleItem]);
    showSample();
    expect((await api.getWorlds({}, [])).data.map((w) => w.id)).toEqual([
      "w_mine",
      SAMPLE_WORLD_ID,
    ]);
    expect(urls()).toEqual(["/worlds?limit=100&include_sample=1"]);
    hideSample();
    expect((await api.getWorlds({}, [])).data.map((w) => w.id)).toEqual(["w_mine"]);
    expect(urls()[1]).toBe("/worlds?limit=100"); // a hidden sample is not even asked for
  });
});

describe("STARTER_1 nothing is written for the sample", () => {
  it("STARTER_1_an_answer_or_pause_on_the_sample_is_simulated_and_sends_no_request", async () => {
    const fetchSpy = vi.fn(async () => json({ outcome: "answered" }));
    const http = new HttpClient({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
    for (const path of [
      `/worlds/${SAMPLE_WORLD_ID}/cards/c1/answer`,
      `/worlds/${SAMPLE_WORLD_ID}/pause`,
      `/worlds/${SAMPLE_WORLD_ID}`,
    ]) {
      await expect(http.postJson(path, { option: "approve" })).rejects.toMatchObject({
        code: "sample_is_a_replay",
        message: expect.stringContaining("simulated"),
      });
    }
    expect(fetchSpy).not.toHaveBeenCalled();
    await http.postJson("/worlds/w_mine/cards/c1/answer", { option: "approve" }); // other worlds are untouched
    await http.postJson(`/worlds/${SAMPLE_WORLD_ID}_2/cards/c1/answer`, {});
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });
});

describe("STARTER_1 the pages", () => {
  const sampleWorlds = (items: WorldListItem[]) => ({
    data: worldsFromList(items),
    source: "live" as const,
  });

  it("STARTER_1_worlds_row_has_the_badge_the_note_and_a_hide_control", async () => {
    const base = liveWorldsApi();
    const api = {
      ...base,
      getWorlds: vi.fn(async () => sampleWorlds([sampleItem])),
    } as unknown as WorldsApi;
    const r = await renderWorlds({ api });
    const row = r.c.querySelector(`a[href$="${SAMPLE_WORLD_ID}"]`) as HTMLElement;
    expect(row.textContent).toContain(TITLE);
    expect(q(row, ".park-sample-badge").textContent).toBe("Sample");
    expect(row.textContent).toContain(SAMPLE_NOTE);
    expect(hasControl(r.c, "Show sample project")).toBe(false);
    await act(async () => {
      control(r.c, "Hide sample project").click();
    });
    await flush();
    expect(isSampleHidden()).toBe(true);
    expect(api.getWorlds).toHaveBeenCalledTimes(2); // read again; the live Api drops it (tested above)
  });

  it("STARTER_1_worlds_offers_show_sample_project_when_it_is_not_listed", async () => {
    const base = liveWorldsApi();
    const api = {
      ...base,
      getWorlds: vi.fn(async () => sampleWorlds([own])),
    } as unknown as WorldsApi;
    const r = await renderWorlds({ api });
    expect(hasControl(r.c, "Hide sample project")).toBe(false);
    await act(async () => {
      control(r.c, "Show sample project").click();
    });
    await flush();
    expect(wantsSample()).toBe(true);
    expect(api.getWorlds).toHaveBeenCalledTimes(2);
  });

  it("STARTER_1_fixture_data_gets_no_sample_controls", async () => {
    const r = await renderWorlds();
    expect(hasControl(r.c, "Show sample project")).toBe(false);
    expect(hasControl(r.c, "Hide sample project")).toBe(false);
  });

  it("STARTER_1_home_card_marks_the_sample", async () => {
    const api = liveSourced({ getWorlds: async () => sampleWorlds([sampleItem]) });
    const rig = await mountLiveHome(api);
    const today = todayRegion(rig.el);
    expect(q(today, ".park-sample-badge").textContent).toBe("Sample");
    expect(today.textContent).toContain(SAMPLE_NOTE);
    await act(async () => {
      (
        Array.from(today.querySelectorAll("button")).find((b) =>
          b.textContent?.includes(TITLE),
        ) as HTMLElement
      ).click();
    });
    expect(rig.navigate).toHaveBeenCalled();
  });

  it("STARTER_1_home_shows_no_sample_row_for_other_worlds", async () => {
    const api = liveSourced({ getWorlds: async () => sampleWorlds([own]) });
    const rig = await mountLiveHome(api);
    expect(todayRegion(rig.el).querySelector(".park-sample-badge")).toBeNull();
  });

  it("STARTER_1_world_page_marks_the_sample_links_the_replay_and_cannot_be_paused", async () => {
    const base = liveWorldsApi();
    const api = { ...base, getWorlds: vi.fn(async () => sampleWorlds([sampleItem])) };
    const rig = await mountWorld({ id: SAMPLE_WORLD_ID, api });
    expect(q(rig.el, ".park-sample-badge").textContent).toBe("Sample");
    expect(pageText(rig.el)).toContain(SAMPLE_NOTE);
    expect(pageText(rig.el)).not.toContain("Owned by");
    expect((control(rig.el, "Watch the replay") as HTMLAnchorElement).getAttribute("href")).toBe(
      `/world/${SAMPLE_WORLD_ID}/stage`,
    );
    expect((control(rig.el, "Pause") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("STARTER_1 the replay banner", () => {
  const ev = (world_id: string) =>
    ({ world_id, run_id: "r_x", ts: "2026-09-29T09:30:02.000Z" }) as unknown as Event;
  it("STARTER_1_replay_banner_says_sample_for_the_sample_world_only", () => {
    expect(replayBanner([ev(SAMPLE_WORLD_ID)], false)).toBe(
      "Replay of run #r_x recorded 29 Sep 2026 · sample project, not your work",
    );
    expect(replayBanner([ev("w_mine")], false)).toBe("Replay of run #r_x recorded 29 Sep 2026");
  });
});
