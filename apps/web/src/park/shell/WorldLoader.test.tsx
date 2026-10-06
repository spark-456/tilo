// @vitest-environment happy-dom
// WEB-3b: <WorldLoader/> and <BootSplash/> (README "Interactions and motion": Open a world, Boot; reference
// `Tilo App.dc.html` wl and boot). Both are STATIC: the spinner is a ring, the bars jump to their width, the
// card and the splash are removed at once (no fade). Pinned surface:
//   park/shell/WorldLoader.tsx: `WorldLoader()`, no props; renders nothing while store.wl is null. Else
//     `div.park-wl[data-testid="world-loader"][role="status"][aria-live="polite"]` (the scrim) >
//     `div.park-wl__card` > `div.park-wl__art` (the world's art from the kit: a Director agent for a City,
//     `art(world)` for a Town or Village; at least one element inside), `div.park-wl__eyebrow`
//     ("OPENING CITY|TOWN|VILLAGE"), `div.park-wl__name`, `div.park-wl__meta` ("<tool> · <n> agent(s)"), three
//     `div.park-wl__step[data-state="done|active|pending"]` (also class `park-wl__step--<state>`) holding
//     `span.park-wl__tick.park-wl__tick--<state>` (done holds an svg tick, active holds
//     `span.park-wl__spin`, pending holds neither), and `div.park-wl__track > div.park-wl__fill` whose inline
//     width is min(100, (step + 1) * 30)% : 30%, 60%, 90%, 100%.
//   park/shell/BootSplash.tsx: `BootSplash({ ready: boolean })`: null when ready; else
//     `div.park-boot[role="status"][aria-label="Loading Tilo"]` with `.park-boot__tile` > `.park-boot__visor`,
//     `.park-boot__word` "tilo", `.park-boot__track > .park-boot__fill` and the text "Loading your city".
import { act, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../test-support/park/componentsHarness";
import { mountShell, seen } from "../../../test-support/park/shellHarness";
import { BootSplash } from "./BootSplash";
import { WorldLoader } from "./WorldLoader";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const loader = () => document.querySelector<HTMLElement>('[data-testid="world-loader"]');
const steps = () => qa(document.body, ".park-wl__step");
const states = () => steps().map((s) => s.getAttribute("data-state"));
const labels = () => steps().map((s) => (s.textContent ?? "").trim());
const width = () => q(document.body, ".park-wl__fill").style.width;
const tick = (sch: ReturnType<typeof mountShell>["sch"]) => act(() => sch.fire(sch.live()[0]));

describe("WEB_3b_loader: nothing until a world is opened", () => {
  it("WEB_3b_loader_renders_nothing_while_wl_is_null", () => {
    mountShell(<WorldLoader />);
    expect(loader()).toBeNull();
  });

  it("WEB_3b_loader_appears_when_openWorld_starts_and_is_a_polite_status_scrim", () => {
    mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("k1"));
    const el = loader() as HTMLElement;
    expect(el).not.toBeNull();
    expect(el.getAttribute("role")).toBe("status");
    expect(el.getAttribute("aria-live")).toBe("polite");
    expect(el.classList.contains("park-wl")).toBe(true);
    expect(qa(el, ".park-wl__card")).toHaveLength(1);
  });

  it("WEB_3b_loader_an_unknown_world_shows_no_loader", () => {
    mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("nope"));
    expect(loader()).toBeNull();
  });
});

describe("WEB_3b_loader: the card for each tier", () => {
  it("WEB_3b_loader_city_shows_the_art_the_eyebrow_name_meta_and_three_steps", () => {
    mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("k1"));
    expect(q(document.body, ".park-wl__art").children.length).toBeGreaterThan(0);
    expect(q(document.body, ".park-wl__eyebrow").textContent).toBe("OPENING CITY");
    expect(q(document.body, ".park-wl__name").textContent).toBe("K1 electric scooter");
    expect(q(document.body, ".park-wl__meta").textContent).toBe("Workspace · 38 agents");
    expect(labels()).toEqual([
      "Loading districts and buildings",
      "Waking 38 agents",
      "Syncing spend and decisions",
    ]);
  });

  it("WEB_3b_loader_town_says_OPENING_TOWN_with_the_routine_steps", () => {
    mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("invoice"));
    expect(q(document.body, ".park-wl__eyebrow").textContent).toBe("OPENING TOWN");
    expect(q(document.body, ".park-wl__name").textContent).toBe("Weekly invoice match");
    expect(q(document.body, ".park-wl__meta").textContent).toBe("Routine · 5 agents");
    expect(labels()).toEqual(["Loading the routine", "Reading run history", "Checking the next run"]);
    expect(q(document.body, ".park-wl__art").children.length).toBeGreaterThan(0);
  });

  it("WEB_3b_loader_village_says_OPENING_VILLAGE_and_the_meta_is_singular_for_one_agent", () => {
    mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("comp"));
    expect(q(document.body, ".park-wl__eyebrow").textContent).toBe("OPENING VILLAGE");
    expect(q(document.body, ".park-wl__meta").textContent).toBe("Quick task · 1 agent");
    expect(labels()).toEqual(["Loading the task", "Checking progress", "Fetching results"]);
    expect(q(document.body, ".park-wl__art").children.length).toBeGreaterThan(0);
  });

  it("WEB_3b_loader_village_with_two_agents_is_plural", () => {
    mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("venues"));
    expect(q(document.body, ".park-wl__meta").textContent).toBe("Quick task · 2 agents");
  });

  it("WEB_3b_loader_a_world_the_user_started_opens_with_its_own_name", () => {
    mountShell(<WorldLoader />);
    act(() => {
      seen.store.addWorld("routine", "Every Monday, match invoices");
    });
    act(() => seen.store.openWorld("new1"));
    expect(q(document.body, ".park-wl__eyebrow").textContent).toBe("OPENING TOWN");
    expect(q(document.body, ".park-wl__name").textContent).toBe("Every Monday, match invoices");
  });
});

describe("WEB_3b_loader: the steps tick from spinner to check (static, no animation)", () => {
  it("WEB_3b_loader_step_0_has_one_spinner_and_two_pending", () => {
    mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("k1"));
    expect(states()).toEqual(["active", "pending", "pending"]);
    expect(qa(steps()[0] as HTMLElement, ".park-wl__spin")).toHaveLength(1);
    expect(qa(document.body, ".park-wl__spin")).toHaveLength(1);
    expect(qa(document.body, ".park-wl__step svg")).toHaveLength(0);
    expect(steps().map((el) => el.classList.contains(`park-wl__step--${el.getAttribute("data-state")}`))).toEqual([true, true, true]);
    expect(qa(document.body, ".park-wl__tick--active")).toHaveLength(1);
    expect(qa(document.body, ".park-wl__tick--pending")).toHaveLength(2);
    expect(width()).toBe("30%");
  });

  it("WEB_3b_loader_each_tick_turns_the_spinner_into_a_check_and_widens_the_bar", () => {
    const { sch } = mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("k1"));
    tick(sch);
    expect(states()).toEqual(["done", "active", "pending"]);
    expect(qa(steps()[0] as HTMLElement, "svg")).toHaveLength(1);
    expect(qa(steps()[1] as HTMLElement, ".park-wl__spin")).toHaveLength(1);
    expect(width()).toBe("60%");
    tick(sch);
    expect(states()).toEqual(["done", "done", "active"]);
    expect(width()).toBe("90%");
    tick(sch);
    expect(states()).toEqual(["done", "done", "done"]);
    expect(qa(document.body, ".park-wl__spin")).toHaveLength(0);
    expect(qa(document.body, ".park-wl__step svg")).toHaveLength(3);
    expect(width()).toBe("100%");
  });

  it("WEB_3b_loader_the_card_is_removed_on_the_last_tick_with_no_fade_left_behind", () => {
    const { sch } = mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("comp"));
    tick(sch);
    tick(sch);
    tick(sch);
    expect(loader()).not.toBeNull();
    tick(sch);
    expect(loader()).toBeNull();
    expect(document.body.querySelector(".park-wl")).toBeNull();
  });

  it("WEB_3b_loader_no_inline_style_animates_or_transitions", () => {
    const { sch } = mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("k1"));
    for (let i = 0; i < 3; i++) {
      for (const el of qa(document.body, "[style]")) {
        expect(el.getAttribute("style") ?? "").not.toMatch(/transition|animation/i);
      }
      tick(sch);
    }
  });

  it("WEB_3b_loader_opening_another_world_swaps_the_card_to_that_world_at_step_0", () => {
    const { sch } = mountShell(<WorldLoader />);
    act(() => seen.store.openWorld("k1"));
    tick(sch);
    act(() => seen.store.openWorld("comp"));
    expect(q(document.body, ".park-wl__name").textContent).toBe("Competitor pricing");
    expect(states()).toEqual(["active", "pending", "pending"]);
    expect(width()).toBe("30%");
  });
});

describe("WEB_3b_boot: the splash", () => {
  it("WEB_3b_boot_while_not_ready_it_shows_the_logo_the_bar_and_Loading_your_city", () => {
    const { m } = mountShell(<BootSplash ready={false} />);
    const el = q(m.container, ".park-boot");
    expect(el.getAttribute("role")).toBe("status");
    expect(el.getAttribute("aria-label")).toBe("Loading Tilo");
    expect(qa(el, ".park-boot__tile .park-boot__visor")).toHaveLength(1);
    expect(q(el, ".park-boot__word").textContent).toBe("tilo");
    expect(qa(el, ".park-boot__track .park-boot__fill")).toHaveLength(1);
    expect(el.textContent).toContain("Loading your city");
  });

  it("WEB_3b_boot_when_ready_it_renders_nothing", () => {
    const { m } = mountShell(<BootSplash ready />);
    expect(m.container.querySelector(".park-boot")).toBeNull();
    expect(m.container.querySelector('[aria-label="Loading Tilo"]')).toBeNull();
  });

  it("WEB_3b_boot_it_is_removed_the_moment_ready_turns_true", () => {
    let setReady: (v: boolean) => void = () => undefined;
    function Host() {
      const [ready, set] = useState(false);
      setReady = set;
      return <BootSplash ready={ready} />;
    }
    const { m } = mountShell(<Host />);
    expect(m.container.querySelector(".park-boot")).not.toBeNull();
    act(() => setReady(true));
    expect(m.container.querySelector(".park-boot")).toBeNull();
    act(() => setReady(false));
    expect(m.container.querySelector(".park-boot")).not.toBeNull();
  });

  it("WEB_3b_boot_the_bar_is_a_static_element_with_no_style_animation", () => {
    const { m } = mountShell(<BootSplash ready={false} />);
    for (const el of qa(m.container, ".park-boot, .park-boot *")) {
      expect(el.getAttribute("style") ?? "").not.toMatch(/transition|animation/i);
    }
  });
});
