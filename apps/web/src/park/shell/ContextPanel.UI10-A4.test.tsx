// @vitest-environment happy-dom
// UI-10 / A4 (14 Oct QA, "Your context"): closed on every load (a stored "open" no longer reopens it over the
// page), Esc and a click on the backdrop close it, nothing is left behind when it is closed, and the sheet is
// styled with role tokens (no default bullets, no literal colours).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { type ReactNode, act } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, click, mount, pressDocument } from "../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../api/fixtureApi";
import { ParkProvider } from "../app/context";
import { ContextPanel, useContextChoice } from "./ContextPanel";

const api = createFixtureApi();
const mounted = (child: ReactNode) => mount(<ParkProvider api={api}>{child}</ParkProvider>);
const settle = async () => {
  await act(async () => undefined);
};
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function Control({ person }: { person: string }) {
  const [open, toggle] = useContextChoice(person);
  return (
    <>
      <button type="button" aria-expanded={open} onClick={toggle}>
        Context
      </button>
      {open && <ContextPanel onClose={toggle} />}
    </>
  );
}

// the key the panel used to keep its choice under (FNV-1a of the lower-cased person)
const legacyKey = (person: string): string => {
  let hash = 0x811c9dc5;
  for (const c of person.trim().toLowerCase()) hash = Math.imul(hash ^ c.charCodeAt(0), 0x01000193);
  return `tilo.park.context.${(hash >>> 0).toString(16)}`;
};

it("UI_10_A4_a_stored_open_choice_does_not_reopen_the_panel_on_load", async () => {
  const person = "reload-a4@example.test";
  window.localStorage.setItem(legacyKey(person), "1");
  const m = mounted(<Control person={person} />);
  await settle();
  expect(m.container.querySelector("button")?.getAttribute("aria-expanded")).toBe("false");
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(document.querySelector(".park-popover__backdrop")).toBeNull();
});

it("UI_10_A4_opening_the_panel_stores_nothing", async () => {
  const m = mounted(<Control person="store-a4@example.test" />);
  const button = m.container.querySelector("button");
  if (!button) throw new Error("missing context toggle");
  click(button);
  await settle();
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  expect(window.localStorage.length).toBe(0);
});

it("UI_10_A4_Esc_and_the_backdrop_each_close_the_panel_and_leave_no_layer", async () => {
  const m = mounted(<Control person="close-a4@example.test" />);
  const button = m.container.querySelector("button");
  if (!button) throw new Error("missing context toggle");
  click(button);
  await settle();
  pressDocument("Escape");
  await settle();
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(document.querySelector(".park-popover__backdrop")).toBeNull();
  click(button);
  await settle();
  const backdrop = document.querySelector<HTMLElement>(".park-popover__backdrop");
  expect(backdrop).not.toBeNull();
  if (backdrop) click(backdrop);
  await settle();
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(document.querySelector(".park-popover__backdrop")).toBeNull();
});

it("UI_10_A4_the_sheet_is_styled_with_tokens_and_has_no_default_bullets", () => {
  const css = readFileSync(join(__dirname, "ContextPanel.css"), "utf8");
  expect(css).toMatch(/\.park-context ul\s*\{[^}]*list-style:\s*none/);
  expect(css).toContain("var(--pop)");
  expect(css).toContain("var(--shPop)");
  expect(css, "no literal colours").not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(/);
});
