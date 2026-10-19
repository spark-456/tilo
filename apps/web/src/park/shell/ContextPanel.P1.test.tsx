// @vitest-environment happy-dom
import { type ReactNode, act } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, click, mount, pressDocument } from "../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../api/fixtureApi";
import { ParkProvider } from "../app/context";
import { ContextPanel, useContextChoice } from "./ContextPanel";
const fixtureApi = createFixtureApi();
const mounted = (child: ReactNode, api = fixtureApi) =>
  mount(<ParkProvider api={api}>{child}</ParkProvider>);
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});
const settle = async () => {
  await act(async () => undefined);
};
function Control({ person = "a@example.test" }: { person?: string }) {
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
it("test_P1_toggle_shortcut_escape_and_per_person_choice", async () => {
  const m = mounted(<Control />);
  const button = m.container.querySelector("button");
  if (!button) throw new Error("missing context toggle");
  button.focus();
  click(button);
  await settle();
  expect(m.container.querySelector('[role="dialog"]')).not.toBeNull();
  pressDocument("Escape");
  await settle();
  expect(document.activeElement).toBe(button);
  act(() =>
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "c", altKey: true, shiftKey: true, bubbles: true }),
    ),
  );
  await settle();
  expect(button.getAttribute("aria-expanded")).toBe("true");
  m.unmount();
  const other = mounted(<Control person="b@example.test" />);
  expect(other.container.querySelector("button")?.getAttribute("aria-expanded")).toBe("false");
  other.unmount();
  const again = mounted(<Control />);
  await settle();
  expect(again.container.querySelector('[role="dialog"]')).not.toBeNull();
  expect(Object.keys(window.localStorage).join()).not.toContain("example.test");
});
it.each([false, true])("test_P1_provenance_unavailable_and_failed_reads_%s", async (failed) => {
  const fail = () => Promise.reject(new Error("offline"));
  const api = failed
    ? {
        ...fixtureApi,
        getWorlds: fail,
        getDecisions: fail,
        getAgenda: fail,
        getTeam: fail,
        getSkills: fail,
        getConnectors: fail,
        getLedger: fail,
      }
    : { ...fixtureApi, getSkills: fail };
  const m = mounted(<ContextPanel onClose={() => undefined} />, api);
  await settle();
  const text = m.container.textContent;
  for (const title of ["Now", "This project", "Workspace", "Past", "Future", "What Tilo knows"])
    expect(text).toContain(title);
  if (failed) {
    expect(text).toContain("Runs: not available");
    expect(text).not.toContain("Sample data");
  } else expect(text).toContain("Sample data");
  expect(text).toContain("Skills: not available");
  expect(text).toContain("Knowledge items are not available yet");
  expect(text).not.toContain("Loading");
});
