// @vitest-environment happy-dom
// WORLDS-MANAGE (owner, 21 Oct): delete a world from its card or many at once, after a dialog that names them; sort the
// list and pin favourites to the top. Sample data deletes nothing and says so; a live delete happens only on the
// server's answer, a world still at work is paused first.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { cardIds, flush, renderWorlds } from "../../../../test-support/park/worldsHarness";
import type { HttpClient } from "../../../api/http";
import { createFixtureApi } from "../../api/fixtureApi";
import type { World } from "../../api/types";
import { ParkProvider } from "../../app/context";
import { WorldsPage } from "./WorldsPage";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

const byLabel = (c: ParentNode, label: string) =>
  [...c.querySelectorAll<HTMLElement>("button, input")].find(
    (b) => b.getAttribute("aria-label") === label || b.textContent?.trim() === label,
  );
const dialog = (c: ParentNode) => c.querySelector<HTMLElement>(".park-worlds-delete");

describe("WORLDS_MANAGE sample data", () => {
  it("WORLDS_MANAGE_select_and_delete_in_sample_data_says_nothing_was_deleted", async () => {
    const r = await renderWorlds();
    const before = cardIds(r.c, "Your worlds");
    click(byLabel(r.c, "Select") as HTMLElement);
    await flush();
    const first = r.c.querySelector<HTMLInputElement>(".park-worlds-pick input");
    expect(first, "cards turn into checkboxes").not.toBeNull();
    await act(async () => first?.click());
    click(byLabel(r.c, "Delete selected") as HTMLElement);
    await flush();
    expect(dialog(r.c)?.textContent).toMatch(/^Delete “.+”\?/);
    const confirm = [...(dialog(r.c)?.querySelectorAll("button") ?? [])].pop() as HTMLElement;
    click(confirm);
    await flush();
    expect(r.app.toast).toHaveBeenCalledWith(
      expect.stringMatching(/^Sample data: “.+” was not deleted\.$/),
    );
    expect(cardIds(r.c, "Your worlds"), "nothing left the list").toEqual(before);
  });

  it("WORLDS_MANAGE_sort_by_name_and_pin_to_the_top", async () => {
    const r = await renderWorlds();
    const select = r.c.querySelector<HTMLSelectElement>(".park-worlds-sort__select");
    await act(async () => {
      if (!select) return;
      select.value = "name";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const names = [...r.c.querySelectorAll(".park-worlds-card")].map(
      (a) => a.getAttribute("aria-label") ?? "",
    );
    expect(names).toEqual(
      [...names].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" })),
    );
    const last = names[names.length - 1] as string;
    click(byLabel(r.c, `Pin ${last} to the top`) as HTMLElement);
    await flush();
    expect(r.c.querySelector(".park-worlds-card")?.getAttribute("aria-label")).toBe(last);
    expect(byLabel(r.c, `Unpin ${last}`)).toBeDefined();
  });
});

describe("WORLDS_MANAGE live", () => {
  it("WORLDS_MANAGE_a_working_world_is_paused_then_deleted_and_leaves_the_list_on_the_answer", async () => {
    const api = createFixtureApi();
    const base = (await api.getWorlds({}, [])).data[0] as World;
    const worlds: World[] = [
      { ...base, id: "w_busy", name: "Busy world", st: "running", sample: false },
      { ...base, id: "w_done", name: "Done world", st: "finished", sample: false },
    ];
    api.getWorlds = async () => ({ data: worlds, source: "live" as const });
    const calls: string[] = [];
    const client = {
      pauseWorld: vi.fn(async (id: string) => void calls.push(`pause ${id}`)),
      deleteWorld: vi.fn(async (id: string) => void calls.push(`delete ${id}`)),
      getLayout: vi.fn(() => new Promise(() => undefined)),
    } as unknown as HttpClient;
    const app = stubApp("worlds");
    const m = mount(
      <ParkProvider api={api} worldClient={client}>
        <WorldsPage app={app} />
      </ParkProvider>,
    );
    await flush();
    click(byLabel(m.container, "Delete Busy world") as HTMLElement);
    await flush();
    expect(dialog(m.container)?.textContent).toContain("Delete “Busy world”?");
    expect(dialog(m.container)?.textContent).toContain(
      "Pausing also sets your autonomy rules back to Ask first.",
    );
    click(byLabel(dialog(m.container) as HTMLElement, "Stop and delete") as HTMLElement);
    await flush();
    expect(calls).toEqual(["pause w_busy", "delete w_busy"]);
    expect(app.toast).toHaveBeenCalledWith("Deleted “Busy world”.");
    const left = [...m.container.querySelectorAll(".park-worlds-card")].map((a) =>
      a.getAttribute("aria-label"),
    );
    expect(left).toEqual(["Done world"]);
    expect(dialog(m.container)).toBeNull();
  });

  it("WORLDS_MANAGE_one_delete_takes_at_most_fifty_worlds", async () => {
    const api = createFixtureApi();
    const base = (await api.getWorlds({}, [])).data[0] as World;
    api.getWorlds = async () => ({
      data: Array.from({ length: 55 }, (_, i) => ({
        ...base,
        id: `w_${i}`,
        name: `World ${i}`,
        st: "finished" as const,
        sample: false,
      })),
      source: "live" as const,
    });
    const client = {
      pauseWorld: vi.fn(),
      deleteWorld: vi.fn(),
      getLayout: vi.fn(() => new Promise(() => undefined)),
    } as unknown as HttpClient;
    const m = mount(
      <ParkProvider api={api} worldClient={client}>
        <WorldsPage app={stubApp("worlds")} />
      </ParkProvider>,
    );
    await flush();
    click(byLabel(m.container, "Select") as HTMLElement);
    await flush();
    click(byLabel(m.container, "Select the first 50") as HTMLElement);
    await flush();
    expect(m.container.querySelector(".park-worlds-manage__count")?.textContent).toBe(
      "50 selected, the most at once",
    );
    const boxes = [...m.container.querySelectorAll<HTMLInputElement>(".park-worlds-pick input")];
    expect(boxes.filter((b) => b.checked)).toHaveLength(50);
    const left = boxes.filter((b) => !b.checked);
    expect(left.length).toBeGreaterThan(0);
    expect(left.every((b) => b.disabled)).toBe(true);
    click(byLabel(m.container, "Delete selected") as HTMLElement);
    await flush();
    expect(dialog(m.container)?.textContent).toContain("Delete 50 worlds?");
  });

  it("WORLDS_MANAGE_a_refused_delete_keeps_the_world_and_says_why", async () => {
    const api = createFixtureApi();
    const base = (await api.getWorlds({}, [])).data[0] as World;
    api.getWorlds = async () => ({
      data: [{ ...base, id: "w_one", name: "One world", st: "finished", sample: false }],
      source: "live" as const,
    });
    const client = {
      pauseWorld: vi.fn(),
      deleteWorld: vi.fn(async () => {
        throw new Error("Tilo could not find that.");
      }),
      getLayout: vi.fn(() => new Promise(() => undefined)),
    } as unknown as HttpClient;
    const m = mount(
      <ParkProvider api={api} worldClient={client}>
        <WorldsPage app={stubApp("worlds")} />
      </ParkProvider>,
    );
    await flush();
    click(byLabel(m.container, "Delete One world") as HTMLElement);
    await flush();
    click(byLabel(dialog(m.container) as HTMLElement, "Delete") as HTMLElement);
    await flush();
    expect(dialog(m.container)?.querySelector('[role="alert"]')?.textContent).toBe(
      "“One world” was not deleted: Tilo could not find that.",
    );
    expect(m.container.querySelectorAll(".park-worlds-card")).toHaveLength(1);
    expect(client.pauseWorld).not.toHaveBeenCalled();
  });
});
