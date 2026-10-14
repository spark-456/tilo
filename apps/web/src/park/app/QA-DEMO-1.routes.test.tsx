// @vitest-environment happy-dom
// QA-DEMO-1 (agy-bridge/reports/QA-DEMO-1.md), PR C: M2 an unknown world id is "Page not found", m3 disabled lens
// links look and read disabled with the reason written on the page, m5 the Mobile app note closes when the page
// changes, m12 a build stamp tells a deployed build from an older one.
import { readFileSync } from "node:fs";
import path from "node:path";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp, mountShell, settle } from "../../../test-support/park/shellHarness";
import { WorldPage } from "../pages/World/WorldPage";
import { BUILD_SHA } from "./buildStamp";
import { useApp } from "./context";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

function World() {
  return <WorldPage app={useApp()} />;
}
const text = (el: Element | null): string => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const read = (rel: string): string => readFileSync(path.join(__dirname, rel), "utf8");

describe("QA_DEMO_1_M2 an unknown world id", () => {
  it("QA_DEMO_1_M2_shows_page_not_found_and_no_other_job_with_approve_buttons", async () => {
    const rig = mountShell(<World />, { api: fakeApi(), path: "/world/zzz" });
    await settle();
    const c = rig.m.container;
    expect(c.querySelector('[data-testid="park-not-found"]')).not.toBeNull();
    expect(text(c)).toContain("Page not found");
    expect(c.querySelector('[data-testid="park-page-world"]')).toBeNull();
    expect(text(c)).not.toMatch(/Approve/);
    expect(text(c)).not.toContain("K1 electric scooter");
  });

  it("QA_DEMO_1_M2_a_known_id_still_opens_its_world", async () => {
    const rig = mountShell(<World />, { api: fakeApi(), path: "/world/k1" });
    await settle();
    expect(rig.m.container.querySelector('[data-testid="park-page-world"]')).not.toBeNull();
    expect(text(rig.m.container)).toContain("K1 electric scooter");
  });
});

describe("QA_DEMO_1_m3 a world with no recorded run", () => {
  it("QA_DEMO_1_m3_lens_links_are_disabled_and_the_reason_is_visible_text", async () => {
    const rig = mountShell(<World />, { api: fakeApi(), path: "/world/k1" });
    await settle();
    const lenses = qa(rig.m.container, ".park-world-lenses a");
    expect(lenses.map(text)).toEqual(["Story", "Trace", "Delivery", "Inspect"]);
    for (const a of lenses) {
      expect(a.getAttribute("aria-disabled")).toBe("true");
      expect(a.getAttribute("href")).toBeNull();
      expect(a.getAttribute("aria-describedby")).toBe("park-world-nostage");
    }
    const why = q(rig.m.container, "#park-world-nostage");
    expect(why.classList.contains("park-world-sr")).toBe(false); // words on the page, not hidden text
    expect(text(why)).toContain("no recorded run");
  });

  it("QA_DEMO_1_m3_the_disabled_links_are_styled_muted_not_the_pressable_purple", () => {
    const css = read("../pages/World/World.css");
    expect(css).toMatch(
      /\.park-world-lenses a\[aria-disabled="true"\]\s*\{[^}]*color:\s*var\(--ink3\)/,
    );
    expect(css).toMatch(
      /\.park-world-live\[aria-disabled="true"\]\s*\{[^}]*color:\s*var\(--ink3\)/,
    );
  });
});

describe("QA_DEMO_1_m3 the World stylesheet", () => {
  it("QA_DEMO_1_m3_every_block_is_closed_so_the_slack_dialog_rules_after_proposals_apply", () => {
    // a missing "}" after `.park-world-proposals pre` nested every later rule (the Slack dialog, the badge) in it
    const css = read("../pages/World/World.css").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(css.split("{").length).toBe(css.split("}").length);
  });
});

describe("QA_DEMO_1_m5 the Mobile app note", () => {
  it("QA_DEMO_1_m5_closes_when_the_page_changes", async () => {
    await mountApp({ api: fakeApi(), path: "/ledger" });
    click(q(document.body, 'button[aria-label="Account menu"]'));
    const row = qa(document.body, '[role="menuitem"]').find((b) =>
      text(b).startsWith("Mobile app"),
    );
    click(row as Element);
    const note = () => document.querySelector('[role="dialog"][aria-label="Mobile app"]');
    expect(note()).not.toBeNull();
    act(() => {
      window.history.pushState({}, "", "/agenda");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await settle();
    expect(note()).toBeNull();
  });
});

describe("QA_DEMO_1_m12 the build stamp", () => {
  it("QA_DEMO_1_m12_home_footer_names_the_build_and_nothing_else_about_it", async () => {
    const { HomePage } = await import("../pages/Home/HomePage");
    function Home() {
      return <HomePage app={useApp()} />;
    }
    const rig = mountShell(<Home />, { api: fakeApi(), path: "/" });
    await settle();
    const legal = q(rig.m.container, 'nav[aria-label="Legal"]');
    expect(text(legal)).toContain(`Build ${BUILD_SHA}`);
    expect(BUILD_SHA).toMatch(/^[0-9a-z]{3,40}$/);
  });

  it("QA_DEMO_1_m12_the_build_defines_the_sha_and_writes_it_to_a_meta_tag", () => {
    const config = readFileSync(path.join(__dirname, "../../../vite.config.ts"), "utf8");
    expect(config).toContain("__TILO_BUILD_SHA__");
    expect(config).toContain('name: "tilo-build"');
    expect(config).toMatch(/\^\[0-9a-f\]\{7,40\}\$/); // only a hex sha is ever stamped
  });
});
