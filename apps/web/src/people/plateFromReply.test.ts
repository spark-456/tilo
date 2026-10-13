import { expect, it } from "vitest";
import { plateFromReply } from "./plateFromReply";

it("FR_PA_02_03 preserves server groups, order and missing facts without recomputing a fixture plate", () => {
  const body = {
    as_of: "2026-10-09T12:00:00Z",
    truncated: true,
    rows: [
      {
        ref: { kind: "work_item", id: "wi_live" },
        group: "attention",
        title: "Actual task",
        due: null,
        at: null,
      },
      {
        ref: { kind: "card", id: "card_live" },
        group: "rest",
        title: null,
        due: "2026-10-12",
        at: null,
      },
    ],
    parked: [
      {
        ref: { kind: "pin", id: "pin_live" },
        group: "done",
        title: "Finished pin",
        due: null,
        at: "2026-10-08T09:00:00Z",
      },
    ],
  };
  const before = structuredClone(body);
  expect(plateFromReply(body)).toEqual({
    asOf: body.as_of,
    truncated: true,
    rows: [
      { key: "work_item:wi_live", group: "attention", title: "Actual task", due: null, at: null },
      { key: "card:card_live", group: "rest", title: null, due: "2026-10-12", at: null },
      {
        key: "pin:pin_live",
        group: "done",
        title: "Finished pin",
        due: null,
        at: "2026-10-08T09:00:00Z",
      },
    ],
  });
  expect(body).toEqual(before);
  expect(
    plateFromReply({ as_of: body.as_of, truncated: false, rows: [], parked: [] })?.rows,
  ).toEqual([]);
});
it.each([
  null,
  {},
  { as_of: "now", truncated: false, rows: [null], parked: [] },
  { as_of: "now", truncated: false, rows: [], parked: null },
])("FR_PA_02_03 rejects unreadable complete plate replies: %j", (body) => {
  expect(plateFromReply(body)).toBeNull();
});
