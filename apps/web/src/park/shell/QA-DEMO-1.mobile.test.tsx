// @vitest-environment happy-dom
// QA-DEMO-1 (agy-bridge/reports/QA-DEMO-1.md), PR B: the phone shell. B2 the tab strip was a 70px window that read
// "Home" on every page; M1 the first-run banner sat under the fixed nav; M5 the Team table had no cue that it scrolls.
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp } from "../../../test-support/park/shellHarness";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const text = (el: Element | null): string => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
const pageButton = () => q<HTMLButtonElement>(document.body, "button.park-shell__pagebtn");

describe("QA_DEMO_1_B2 the nav on a phone", () => {
  it("QA_DEMO_1_B2_390_names_the_current_page_and_opens_a_menu_of_all_six", async () => {
    const rig = await mountApp({ api: fakeApi(), viewport: { vw: 390, vh: 844 }, path: "/team" });
    expect(qa(rig.m.container, "header nav a")).toHaveLength(0); // the strip is not drawn
    expect(text(pageButton())).toContain("Team");
    expect(pageButton().getAttribute("aria-label")).toMatch(/^Pages, now on Team/);
    click(pageButton());
    const items = qa(document.body, '[role="menu"][aria-label="Pages"] [role="menuitem"]');
    expect(
      items.map((i) =>
        text(i)
          .replace(/Current page|\d+ decisions?/g, "")
          .trim(),
      ),
    ).toEqual(["Home", "Chat", "Worlds", "Skills", "Needs you", "Ledger", "Agenda", "Team"]); // STUDIO-2 Chat, STUDIO-4 Needs you
    // the current page is said in words, and decisions waiting are counted (colour carries nothing alone)
    expect(text(items[7] as Element)).toContain("Current page");
    expect(text(items[4] as Element)).toContain("2 decisions");
  });

  it("QA_DEMO_1_B2_320_choosing_a_page_goes_there_and_closes_the_menu", async () => {
    const rig = await mountApp({ api: fakeApi(), viewport: { vw: 320, vh: 640 }, path: "/" });
    click(pageButton());
    const ledger = qa(document.body, '[role="menuitem"]').find((i) => text(i).startsWith("Ledger"));
    click(ledger as Element);
    expect(rig.navigate).toHaveBeenLastCalledWith("/ledger");
    expect(document.body.querySelector('[role="menu"][aria-label="Pages"]')).toBeNull();
  });

  it("QA_DEMO_1_B2_a_page_without_a_tab_is_still_named", async () => {
    await mountApp({ api: fakeApi(), viewport: { vw: 390, vh: 844 }, path: "/profile" });
    expect(text(pageButton())).toContain("Profile");
  });

  it("QA_DEMO_1_B2_1440_keeps_the_six_tab_strip_and_no_page_menu", async () => {
    const rig = await mountApp({ api: fakeApi(), viewport: { vw: 1440, vh: 900 }, path: "/team" });
    expect(qa(rig.m.container, "header nav a")).toHaveLength(8); // STUDIO-2 Chat, STUDIO-4 Needs you
    expect(document.body.querySelector("button.park-shell__pagebtn")).toBeNull();
  });
});

describe("QA_DEMO_1_M1 the sample banner is never behind the nav", () => {
  it("QA_DEMO_1_M1_on_a_page_the_banner_sits_inside_the_content_column_below_the_nav_padding", async () => {
    await mountApp({ api: fakeApi(), viewport: { vw: 390, vh: 844 }, path: "/team" });
    const banner = document.body.querySelector(".park-first-run-banner");
    expect(banner, "the banner shows for the sample company").not.toBeNull();
    expect(banner?.closest(".park-shell__column")).not.toBeNull();
    expect(banner?.classList.contains("park-first-run-banner--home")).toBe(false);
  });

  it("QA_DEMO_1_M1_on_home_the_banner_is_pinned_under_the_nav_not_in_flow_behind_it", async () => {
    await mountApp({ api: fakeApi(), viewport: { vw: 1440, vh: 900 }, path: "/" });
    const banner = document.body.querySelector(".park-first-run-banner");
    expect(banner?.classList.contains("park-first-run-banner--home")).toBe(true);
    expect(banner?.closest(".park-shell__column")).toBeNull();
  });
});

describe("QA_DEMO_1_M5 the Team table says it scrolls", () => {
  it("QA_DEMO_1_M5_the_members_card_carries_a_sideways_scroll_cue_in_words_and_edge_shadows", () => {
    const css = readFileSync(path.join(__dirname, "../pages/Team/Team.css"), "utf8");
    expect(css).toMatch(
      /\.park-team-members::before\s*\{[^}]*content:\s*"Swipe sideways to see roles/,
    );
    expect(css).toMatch(/\.park-team-scroll\s*\{[^}]*radial-gradient[^}]*no-repeat scroll/);
  });

  it("QA_DEMO_1_m10_the_profile_tab_strip_wraps_on_a_narrow_screen_instead_of_clipping", () => {
    const css = readFileSync(path.join(__dirname, "../pages/Profile/Profile.css"), "utf8");
    expect(css).toMatch(
      /\.park-profile-nav:not\(\.park-profile-nav--wide\)\s*\{[^}]*flex-wrap:\s*wrap/,
    );
  });

  // UI-STUDIO-2: the helper tile stays (it shows the request state) but shrinks to 44px on a phone, and the
  // input's text drops to 19px, so the placeholder still reads beside it.
  it("QA_DEMO_1_m8_the_composer_input_keeps_its_room_on_a_phone", () => {
    const css = readFileSync(path.join(__dirname, "../pages/Home/Home.css"), "utf8");
    const phone = css.slice(css.indexOf("@media (max-width: 840px)"));
    expect(phone).toMatch(/\.park-home-logo\s*\{\s*width:\s*44px;/);
    expect(phone).toMatch(/\.park-home-panel \.park-home-input\s*\{[^}]*font-size:\s*19px;/);
  });
});
