import { describe, expect, it } from "vitest";
import { connectorsFromList } from "./connectorsFromList";

describe("FR_ACC_01_03_04 live connectors mapper", () => {
  it("FR_ACC_01_03 preserves order and served scopes without inventing access or usage", () => {
    const body = {
      connectors: [
        {
          id: "crm",
          name: "Real CRM",
          state: "connected",
          state_known: true,
          scopes: ["contacts.read"],
          expires_at: null,
        },
        {
          id: "mail",
          name: "Real Mail",
          state: "available",
          state_known: false,
          scopes: [],
          expires_at: null,
        },
      ],
    };
    const before = structuredClone(body);
    const rows = connectorsFromList(body);
    expect(rows?.map((c) => c.id)).toEqual(["crm", "mail"]);
    expect(rows?.[0]).toMatchObject({
      name: "Real CRM",
      st: "connected",
      live: { stateKnown: true, scopes: ["contacts.read"] },
    });
    expect(rows?.[1]?.live?.stateKnown).toBe(false);
    for (const c of rows ?? []) {
      for (const key of ["level", "acct", "sync", "used", "scopes"])
        expect(c).not.toHaveProperty(key);
    }
    expect(body).toEqual(before);
    rows?.[0]?.live?.scopes.push("local");
    expect(body.connectors[0]?.scopes).toEqual(["contacts.read"]);
  });
  it("FR_ACC_04 preserves the served attention state and grant expiry", () => {
    expect(
      connectorsFromList({
        connectors: [
          {
            id: "crm",
            name: "CRM",
            state: "attention",
            state_known: true,
            scopes: [],
            expires_at: "2026-10-10T00:00:00Z",
          },
        ],
      })?.[0],
    ).toMatchObject({ st: "attention", expires: "2026-10-10T00:00:00Z" });
    expect(connectorsFromList({ connectors: [] })).toEqual([]);
  });
  it.each([
    null,
    {},
    { connectors: [null] },
    {
      connectors: [
        { id: "x", name: "X", state: "invented", state_known: true, scopes: [], expires_at: null },
      ],
    },
    {
      connectors: [
        {
          id: "x",
          name: "X",
          state: "connected",
          state_known: "yes",
          scopes: [],
          expires_at: null,
        },
      ],
    },
  ])("FR_ACC_03 rejects unreadable replies: %j", (body) => {
    expect(connectorsFromList(body)).toBeNull();
  });
});
