// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../test-support/park/componentsHarness";
import { mountApp } from "../../../test-support/park/shellHarness";
import { createFixtureApi } from "../api/fixtureApi";
import { userOf } from "../api/liveApi";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

it.each([
  ["", "", null],
  ["Example", "", "Example"],
  ["", "Team", "Team plan"],
  ["Example", "Team", "Example · Team plan"],
  ["  ", "  ", null],
])("FR_UX_10 account detail joins only present org %s and plan %s", async (org, plan, detail) => {
  const api = createFixtureApi();
  const user = userOf({ name: "Ana Silva", email: "person@example.test" });
  expect(user).not.toBeNull();
  if (!user) throw new Error("Expected a display user");
  api.getUser = async () => ({ data: { ...user, org, plan }, source: "live" });
  await mountApp({ api });
  const avatar = document.querySelector<HTMLButtonElement>('button[aria-label="Account menu"]');
  expect(avatar?.textContent).toBe("AS");
  if (!avatar) throw new Error("Expected the account button");
  click(avatar);
  expect(document.querySelector(".park-shell__whoav")?.textContent).toBe("AS");
  expect(document.querySelector(".park-shell__whoorg")?.textContent ?? null).toBe(detail);
});
