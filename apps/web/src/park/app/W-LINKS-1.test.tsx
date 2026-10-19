// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { MorePage } from "../pages/Team/MorePage";
import { ParkProvider, useApp } from "./context";

afterEach(cleanup);

function More() {
  const app = useApp();
  return <MorePage app={{ ...app, params: { world: "w_a b" } }} />;
}

it("W-LINKS-1 More links open Park sections directly and preserve the selected world", () => {
  const m = mount(
    <ParkProvider>
      <More />
    </ParkProvider>,
  );
  for (const [label, path] of [
    ["Autonomy", "/settings?section=autonomy&world=w_a%20b"],
    ["Channels", "/settings?section=channels&world=w_a%20b"],
    ["How we estimate", "/settings?section=estimate&world=w_a%20b"],
    ["Pilot", "/settings?section=pilot&world=w_a%20b"],
  ]) {
    const link = [...m.container.querySelectorAll("a")].find((a) => a.textContent === label);
    expect(link?.getAttribute("href"), label).toBe(path);
  }
});

it("W-LINKS-1 navigation sources no longer link to retired flow and admin addresses", () => {
  // These literals are navigation destinations, not API endpoints or bookmark redirect tables.
  for (const path of [
    "../pages/Settings/SettingsPage.tsx",
    "../shared/RunAdmin.tsx",
    "../../worldView/DeliveryView.tsx",
    "../../worldView/StageRail.tsx",
  ]) {
    const source = readFileSync(new URL(path, import.meta.url), "utf8");
    expect(source, path).not.toMatch(/"\/(?:start|connections|channels|pilot|estimate)"/);
  }
});
