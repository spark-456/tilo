// @vitest-environment happy-dom
import { StrictMode, act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { worlds } from "../api/fixtures/worlds";
import type { Api } from "../api/index";
import type { ApiResult, World } from "../api/types";
import { ParkProvider, useParkApi, useParkStore } from "../app/context";
import type { ParkStore } from "../app/store";
import { useFirstRun } from "./useFirstRun";

afterEach(cleanup);
const real = { ...worlds({}, [])[0], id: "w_first_real", sample: false } as World;
const sample = { ...real, id: "w_sample_village_basic", sample: true };
let store: ParkStore;
let api: Api;
function Probe({ id = "a" }: { id?: string }) {
  const first = useFirstRun();
  store = useParkStore();
  api = useParkApi();
  return <output data-testid={id}>{String(first)}</output>;
}
function setup(list: World[] = [], source: "live" | "fixture" = "live", copies = 1) {
  const fake = fakeApi();
  const get = vi.fn(async (): Promise<ApiResult<World[]>> => ({ data: list, source }));
  fake.getWorlds = get;
  const node = mount(
    <ParkProvider api={fake} schedule={fakeScheduler().schedule}>
      {["first", "second", "third"].slice(0, copies).map((id) => (
        <Probe key={id} id={id} />
      ))}
    </ParkProvider>,
  );
  return { fake, get, node, value: () => node.container.querySelector("output")?.textContent };
}
const flush = () => act(async () => undefined);

describe("FIRST_RUN_HR_1 shared session guard", () => {
  it("FIRST_RUN_HR_1_empty_live_account_is_sample_only_after_the_worlds_read", async () => {
    const rig = setup();
    expect(rig.value()).toBe("false");
    await flush();
    expect(rig.value()).toBe("true");
    expect(rig.get).toHaveBeenCalledWith({}, []);
  });
  it("FIRST_RUN_HR_1_sample_world_does_not_count_as_a_personal_run", async () => {
    const rig = setup([sample]);
    await flush();
    expect(rig.value()).toBe("true");
  });
  it("FIRST_RUN_HR_1_any_real_world_hides_samples_even_beside_a_sample", async () => {
    const rig = setup([sample, real]);
    await flush();
    expect(rig.value()).toBe("false");
  });
  it("FIRST_RUN_HR_1_fixture_session_keeps_its_existing_sample_behavior", async () => {
    const rig = setup([real], "fixture");
    await flush();
    expect(rig.value()).toBe("true");
  });
  it("FIRST_RUN_HR_1_consumers_share_one_read_and_make_no_writes", async () => {
    const rig = setup([], "live", 3);
    await flush();
    expect(rig.get).toHaveBeenCalledTimes(1);
    expect([...rig.node.container.querySelectorAll("output")].map((n) => n.textContent)).toEqual([
      "true",
      "true",
      "true",
    ]);
    for (const call of [rig.fake.startWorld, rig.fake.decide, rig.fake.undo, rig.fake.setPref])
      expect(call).not.toHaveBeenCalled();
  });
  it("FIRST_RUN_HR_1_read_failure_never_authorizes_sample_content", async () => {
    const fake = fakeApi();
    fake.getWorlds = vi.fn(async () => {
      throw new Error("unavailable");
    });
    const node = mount(
      <ParkProvider api={fake}>
        <Probe />
      </ParkProvider>,
    );
    await flush();
    expect(node.container.textContent).toBe("false");
  });
  it("FIRST_RUN_HR_1_real_start_hides_samples_on_the_next_store_render", async () => {
    const rig = setup();
    await flush();
    expect(rig.value()).toBe("true");
    rig.fake.startWorld.mockResolvedValue({ data: { world: real }, source: "live" });
    await act(async () => {
      expect(await store.startWorld("quick", "a task")).toBe(true);
    });
    expect(rig.value()).toBe("false");
  });
  it("FIRST_RUN_HR_1_refused_start_keeps_first_run_mode", async () => {
    const rig = setup();
    await flush();
    rig.fake.startWorld.mockRejectedValue(new Error("refused"));
    await act(async () => {
      expect(await store.startWorld("quick", "a task")).toBe(false);
    });
    expect(rig.value()).toBe("true");
  });
  it("FIRST_RUN_HR_1_demo_start_keeps_sample_mode", async () => {
    const rig = setup([], "fixture");
    await flush();
    rig.fake.startWorld.mockResolvedValue({ data: { world: real }, source: "fixture" });
    await act(async () => {
      await store.startWorld("quick", "a task");
    });
    expect(rig.value()).toBe("true");
  });
  it("FIRST_RUN_HR_1_failed_worlds_refresh_hides_sample_content", async () => {
    const rig = setup();
    await flush();
    rig.get.mockRejectedValue(new Error("unavailable"));
    await act(async () => {
      await expect(api.getWorlds({}, [])).rejects.toThrow("unavailable");
    });
    expect(rig.value()).toBe("false");
  });
  it("FIRST_RUN_HR_1_effect_replay_can_load_again_without_accepting_a_stale_read", async () => {
    const fake = fakeApi();
    fake.getWorlds = vi.fn(async () => ({ data: [], source: "live" as const }));
    const node = mount(
      <StrictMode>
        <ParkProvider api={fake}>
          <Probe />
        </ParkProvider>
      </StrictMode>,
    );
    await flush();
    expect(node.container.textContent).toBe("true");
  });
  it("FIRST_RUN_HR_1_new_worlds_reads_update_every_consumer_and_empty_replays_cannot_restore_samples", async () => {
    const rig = setup();
    await flush();
    rig.get.mockResolvedValue({ data: [real], source: "live" });
    await act(async () => {
      await api.getWorlds({}, []);
    });
    expect(rig.value()).toBe("false");
    rig.get.mockResolvedValue({ data: [], source: "live" });
    await act(async () => {
      await api.getWorlds({}, []);
    });
    expect(rig.value()).toBe("false");
  });
  it("FIRST_RUN_HR_1_second_person_with_a_real_world_never_inherits_first_person_mode", async () => {
    const first = setup();
    await flush();
    expect(first.value()).toBe("true");
    first.node.unmount();
    const second = setup([real]);
    expect(second.value()).toBe("false");
    await flush();
    expect(second.value()).toBe("false");
  });
  it("FIRST_RUN_HR_1_unmounted_read_cannot_change_the_next_person", async () => {
    let finish!: (answer: ApiResult<World[]>) => void;
    const fake = fakeApi();
    fake.getWorlds = vi.fn(
      () =>
        new Promise<ApiResult<World[]>>((resolve) => {
          finish = resolve;
        }),
    );
    const first = mount(
      <ParkProvider api={fake}>
        <Probe />
      </ParkProvider>,
    );
    first.unmount();
    const second = setup([real]);
    await flush();
    await act(async () => finish({ data: [], source: "live" }));
    expect(second.value()).toBe("false");
  });
});
