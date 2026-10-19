// @vitest-environment happy-dom
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { connectors } from "../../api/fixtures";
import { BrandIcon, colorLogoOf, logoOf } from "./BrandIcon";
import { LiveConnectors } from "./LiveConnectors";
import { groupConnectors } from "./connectorGroups";

afterEach(cleanup);

it("CX_LOGOS_2_bundles_colour_connector_marks_and_keeps_lazy_local_images", () => {
  for (const id of ["gmail", "google_calendar", "google_drive", "slack", "notion", "lovable"]) {
    const path = colorLogoOf(id);
    expect(path, id).toMatch(/^\/park\/brands\/[a-z-]+\.svg$/);
    expect(existsSync(resolve(process.cwd(), `public${path}`)), id).toBe(true);
  }
  const rig = mount(<BrandIcon id="gmail" mono="G" />);
  const img = rig.container.querySelector("img");
  expect(img?.getAttribute("src")).toBe("/park/brands/google-gmail.svg");
  expect(img?.getAttribute("loading")).toBe("lazy");
  expect(img?.getAttribute("alt")).toBe("");
});

it("CX_LOGOS_2_local_artwork_stays_below_300_kib_and_carries_the_mit_notice", () => {
  const root = resolve(process.cwd(), "public/park");
  const bytes = ["brands", "skills"].flatMap((dir) =>
    readdirSync(resolve(root, dir))
      .filter((name) => name.endsWith(".svg"))
      .map((name) => statSync(resolve(root, dir, name)).size),
  );
  expect(bytes.reduce((sum, size) => sum + size, 0)).toBeLessThan(300 * 1024);
  expect(readFileSync(resolve(root, "skills/LICENSE.txt"), "utf8")).toContain("MIT License");
});

it("test_FR_CON_01_connector_logos_cover_every_listed_id_with_a_brand_or_fallback", () => {
  const registry = readFileSync(resolve(process.cwd(), "../../config/connectors.yaml"), "utf8");
  const ids = [...registry.matchAll(/^- id: ([a-z0-9_]+)/gm)].map((match) => match[1]);
  for (const id of [...ids, ...connectors.map((c) => c.id), "canva"]) {
    const rig = mount(<BrandIcon id={id ?? ""} mono="X" />);
    expect(rig.container.querySelector("img, svg, [data-monogram]"), id).not.toBeNull();
    rig.unmount();
  }
  for (const id of [
    "gmail",
    "google_calendar",
    "google_drive",
    "google_docs",
    "google_sheets",
    "google_slides",
    "github",
    "xero",
    "stripe",
  ]) {
    expect(logoOf(id), id).not.toBeNull();
  }
  for (const id of ["lovable", "canva", "slack", "microsoft365", "bamboohr"]) {
    expect(logoOf(id), `${id} is not in Simple Icons 16.35.0`).toBeNull();
  }
  expect(logoOf("unlisted-vendor")).toBeNull();
});

it("test_FR_CON_01_connector_logos_group_only_returned_live_connectors", () => {
  const base = connectors[0];
  if (!base) throw new Error("connector fixture is empty");
  const live = [
    { ...base, id: "gmail", name: "Gmail" },
    { ...base, id: "google_drive", name: "Google Drive" },
    { ...base, id: "canva", name: "Canva" },
  ];
  const groups = groupConnectors(live);
  expect(groups.flatMap((group) => group.connectors.map((c) => c.id))).toEqual(
    live.map((c) => c.id),
  );
  expect(groups.map((group) => group.heading)).toEqual(["Email", "Files", "Build"]);
  const rig = mount(<LiveConnectors connectors={live} />);
  expect(
    [...rig.container.querySelectorAll(".park-connectors-category h2")].map((h) => h.textContent),
  ).toEqual(["Email", "Files", "Build"]);
  expect(rig.container.querySelectorAll("article.park-connectors-live")).toHaveLength(3);
  act(() => rig.unmount());
});
