// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount, q } from "../../../test-support/park/componentsHarness";
import type { HttpClient } from "../../api/http";
import { createFixtureApi } from "../api/fixtureApi";
import { ParkProvider } from "../app/context";
import { RememberChip } from "./RememberChip";

afterEach(cleanup);
const suggestion = { text: "I prefer mornings", kind: "preference" as const };

it("MI-04 Remember waits for the POST reply, and Not now writes nothing", async () => {
  let answer!: (v: unknown) => void;
  const postJson = vi.fn(
    () =>
      new Promise<unknown>((resolve) => {
        answer = resolve;
      }),
  );
  const client = { postJson } as unknown as HttpClient;
  const m = mount(
    <ParkProvider api={createFixtureApi()} worldClient={client}>
      <RememberChip suggestion={suggestion} />
    </ParkProvider>,
  );
  act(() => q<HTMLButtonElement>(m.container, "button").click());
  expect(postJson).toHaveBeenCalledWith("/v1/memory", { ...suggestion, source: "tilo_suggested" });
  expect(m.container.textContent).not.toContain("Saved");
  await act(async () =>
    answer({
      id: "mem_1",
      org_id: "org_1",
      owner: "user_1",
      ...suggestion,
      source: "tilo_suggested",
      created_at: "2026-10-16T00:00:00Z",
      updated_at: "2026-10-16T00:00:00Z",
    }),
  );
  expect(m.container.textContent).toContain("Saved");
  const second = mount(
    <ParkProvider api={createFixtureApi()} worldClient={client}>
      <RememberChip suggestion={suggestion} />
    </ParkProvider>,
  );
  act(() => q<HTMLButtonElement>(second.container, "button:last-of-type").click());
  expect(second.container.textContent).not.toContain("Remember “");
  expect(postJson).toHaveBeenCalledTimes(1);
});
