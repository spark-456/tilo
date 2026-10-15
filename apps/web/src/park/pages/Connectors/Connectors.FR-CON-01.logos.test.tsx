// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { connectors } from "../../api/fixtures";
import { BrandIcon, logoOf } from "./BrandIcon";
import { LiveConnectors } from "./LiveConnectors";
import { groupConnectors } from "./connectorGroups";

afterEach(cleanup);

it("test_FR_CON_01_connector_logos_cover_every_listed_id_with_a_brand_or_fallback", () => {
  const registry = readFileSync(resolve(process.cwd(), "../../config/connectors.yaml"), "utf8");
  const ids = [...registry.matchAll(/^- id: ([a-z0-9_]+)/gm)].map((match) => match[1]);
  for (const id of [...ids, ...connectors.map((c) => c.id), "canva"]) {
    const rig = mount(<BrandIcon id={id ?? ""} mono="X" />);
    expect(
      rig.container.querySelector("svg") ?? rig.container.querySelector("[data-monogram]"),
      id,
    ).not.toBeNull();
    rig.unmount();
  }
  for (const id of ["gmail", "google_calendar", "google_drive", "github", "xero", "stripe"]) {
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
