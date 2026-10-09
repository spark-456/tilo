import { expect, it } from "vitest";
import { decisionKey } from "./decisionsFromCards";
import { notificationsFromList } from "./notificationsFromList";

it("FR_UX_11 maps served titles, timestamps and world links without invented descriptions", () => {
  const body = {
    count: 2,
    notifications: [
      {
        id: "c:card",
        kind: "needs",
        created_at: "2026-10-09T10:00:00Z",
        world_id: "w/1",
        title: "A decision is waiting for you",
        card_id: "card",
        artifact_id: null,
      },
      {
        id: "e:event",
        kind: "done",
        created_at: "2026-10-09T09:00:00Z",
        world_id: "w/2",
        title: "An item is ready",
        card_id: null,
        artifact_id: "art_1",
      },
    ],
  };
  const copy = structuredClone(body);
  expect(notificationsFromList(body)).toEqual([
    {
      id: "c:card",
      kind: "needs",
      t: "2026-10-09T10:00:00Z",
      title: "A decision is waiting for you",
      sub: "",
      go: ["world", "w/1"],
      dec: decisionKey("w/1", "card"),
    },
    {
      id: "e:event",
      kind: "done",
      t: "2026-10-09T09:00:00Z",
      title: "An item is ready",
      sub: "",
      go: ["world", "w/2"],
    },
  ]);
  expect(body).toEqual(copy);
  expect(notificationsFromList({ count: 0, notifications: [] })).toEqual([]);
});
it.each([
  null,
  {},
  { count: 1, notifications: [null] },
  { count: 0, notifications: [{ id: "x" }] },
])("FR_UX_11 rejects unreadable bell replies: %j", (body) => {
  expect(notificationsFromList(body)).toBeNull();
});
