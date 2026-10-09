// ONBOARD-1: the optional last step offers the read-only sample project only when GET /worlds marks one
// (`sample: true`, STARTER-1). Anything else, including a failed call, leaves it out.
import { describe, expect, it } from "vitest";
import { findSampleWorldId } from "./sampleWorld";

const page = (worlds: unknown[]) => ({ worlds, next_cursor: null });

describe("ONBOARD_1_sample: feature-detect the sample world from the worlds list", () => {
  it("ONBOARD_1_sample_found_when_an_item_has_sample_true", async () => {
    const id = await findSampleWorldId(async () =>
      page([
        { world_id: "w_mine", status: "idle", title: "Mine", created_at: null, last_seq: 0 },
        { world_id: "w_sample_village_basic", status: "completed", sample: true },
      ]),
    );
    expect(id).toBe("w_sample_village_basic");
  });

  it("ONBOARD_1_sample_absent_when_no_item_is_marked", async () => {
    expect(
      await findSampleWorldId(async () => page([{ world_id: "w_mine", status: "idle" }])),
    ).toBe(null);
    expect(await findSampleWorldId(async () => page([]))).toBe(null);
    expect(await findSampleWorldId(async () => page([{ world_id: "w_x", sample: "true" }]))).toBe(
      null,
    );
  });

  it("ONBOARD_1_sample_absent_when_the_call_fails_or_the_reply_is_unreadable", async () => {
    expect(
      await findSampleWorldId(async () => {
        throw new Error("offline");
      }),
    ).toBe(null);
    expect(await findSampleWorldId(async () => "nope")).toBe(null);
    expect(await findSampleWorldId(async () => ({ worlds: "nope" }))).toBe(null);
  });

  it("ONBOARD_1_sample_absent_when_there_is_no_reader", async () => {
    expect(await findSampleWorldId(null)).toBe(null);
  });

  it("ONBOARD_1_sample_ignores_an_id_that_is_not_a_plain_world_id", async () => {
    expect(await findSampleWorldId(async () => page([{ world_id: "../etc", sample: true }]))).toBe(
      null,
    );
  });
});
