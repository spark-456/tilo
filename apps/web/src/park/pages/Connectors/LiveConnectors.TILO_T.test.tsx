// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { typeInto } from "../../../../test-support/park/connectorsDom";
import type { Connector } from "../../api/types";
import { LiveConnectors } from "./LiveConnectors";

afterEach(cleanup);

it("CX-T-CONNECTORS groups real connections with counts and manage actions", () => {
  const base: Connector = {
    id: "gmail",
    name: "Gmail",
    st: "connected",
    cat: "",
    mono: "G",
    col: "var(--ink2)",
    live: { stateKnown: true, scopes: ["mail.read"] },
  };
  const rig = mount(
    <LiveConnectors
      connectors={[
        base,
        { ...base, id: "google_calendar", name: "Google Calendar", st: "attention" },
      ]}
      onManage={() => undefined}
    />,
  );
  const groups = [...rig.container.querySelectorAll(".park-connectors-category")];
  expect(groups.map((group) => group.querySelector("h2")?.textContent)).toEqual([
    "Email",
    "Calendar",
  ]);
  expect(
    groups.map((group) => group.querySelector(".park-connectors-group-count")?.textContent),
  ).toEqual(["1 app", "1 app"]);
  const cards = [...rig.container.querySelectorAll("article.park-connectors-live")];
  expect(cards).toHaveLength(2);
  expect(cards[0]?.textContent).toContain("mail.read");
  expect(cards[1]?.textContent).toContain("Needs attention");
  expect(rig.container.querySelectorAll("button[aria-label^='Manage ']")).toHaveLength(2);
  typeInto(
    rig.container.querySelector('input[aria-label="Search connectors"]') as HTMLInputElement,
    "Calendar",
  );
  expect(rig.container.querySelectorAll(".park-connectors-category")).toHaveLength(1);
  expect(rig.container.querySelector(".park-connectors-group-count")?.textContent).toBe("1 app");
});
