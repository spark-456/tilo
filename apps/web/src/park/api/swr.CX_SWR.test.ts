import { expect, it, vi } from "vitest";
import type { Api } from "./index";
import { FRESH_MS, withSwr } from "./swr";

const result = (data: unknown, source: "live" | "fixture" = "live") => ({ data, source });

function rig(person: { value: string | null } = { value: "a@example.com" }) {
  let clock = 1_000;
  const reads = vi.fn(async () => result([{ id: "w1" }]));
  const writes = vi.fn(async () => result({ ok: true }));
  const changed = vi.fn();
  const live = { getLedger: reads, getSkills: reads, decide: writes } as unknown as Api;
  const api = withSwr(
    live,
    () => person.value,
    changed,
    () => clock,
  );
  return {
    api,
    reads,
    writes,
    changed,
    tick: (ms: number) => {
      clock += ms;
    },
    person,
  };
}

it("CX_SWR_a_second_read_answers_from_memory_without_asking_the_server_again", async () => {
  const { api, reads } = rig();
  await api.getLedger();
  await api.getLedger();
  expect(reads).toHaveBeenCalledTimes(1);
});

it("CX_SWR_a_stale_read_answers_at_once_and_refreshes_in_the_background", async () => {
  const { api, reads, changed, tick } = rig();
  await api.getLedger();
  tick(FRESH_MS + 1);
  reads.mockResolvedValueOnce(result([{ id: "w1" }, { id: "w2" }]));
  const stale = await api.getLedger();
  expect(stale.data).toEqual([{ id: "w1" }]); // the page shows what it had
  await vi.waitFor(() => expect(changed).toHaveBeenCalledTimes(1)); // and is told when newer data landed
  expect(reads).toHaveBeenCalledTimes(2);
  expect((await api.getLedger()).data).toEqual([{ id: "w1" }, { id: "w2" }]);
});

it("CX_SWR_unchanged_data_does_not_ask_the_page_to_re_read", async () => {
  const { api, reads, changed, tick } = rig();
  await api.getLedger();
  tick(FRESH_MS + 1);
  await api.getLedger();
  await vi.waitFor(() => expect(reads).toHaveBeenCalledTimes(2));
  expect(changed).not.toHaveBeenCalled();
});

it("CX_SWR_nothing_is_kept_across_people_or_for_a_demo_session", async () => {
  const person = { value: "a@example.com" as string | null };
  const { api, reads } = rig(person);
  await api.getLedger();
  person.value = "b@example.com";
  await api.getLedger(); // another person: a fresh read, never a's answer
  expect(reads).toHaveBeenCalledTimes(2);
  person.value = null; // a demo session has no identity
  await api.getLedger();
  await api.getLedger();
  expect(reads).toHaveBeenCalledTimes(4);
});

it("CX_SWR_fixture_answers_and_failures_are_never_kept", async () => {
  const { api, reads } = rig();
  reads.mockResolvedValueOnce(result([], "fixture"));
  await api.getLedger();
  await api.getLedger();
  expect(reads).toHaveBeenCalledTimes(2);
  reads.mockRejectedValueOnce(new Error("down"));
  await expect(api.getSkills()).rejects.toThrow("down");
  await api.getSkills();
  expect(reads).toHaveBeenCalledTimes(4);
});

it("CX_SWR_a_write_clears_what_was_read_so_a_page_never_shows_the_old_answer", async () => {
  const { api, reads } = rig();
  await api.getLedger();
  await (api as unknown as { decide: () => Promise<unknown> }).decide();
  await api.getLedger();
  expect(reads).toHaveBeenCalledTimes(2);
});
