// PPL-40a: the fixtures S-26 and S-27 read are the contracts/fixtures records they copy, or are
// derived from them (never invented shapes). The JSON is read here, in the test only.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MEETINGS, MINUTES, WORK_ITEMS } from "./data";
import persons from "./fixtures/persons.json";

const root = fileURLToPath(new URL("../../../../contracts/fixtures/", import.meta.url));
const json = (path: string): unknown => JSON.parse(readFileSync(`${root}${path}`, "utf8"));

describe("PPL-40a fixtures stay the contract fixtures they copy", () => {
  it("PPL_40a the Q4 minutes and the two people are the contracts/fixtures records", () => {
    expect(MINUTES[0]).toEqual(json("minutes/valid/q4_plan.json"));
    expect(persons).toEqual([
      json("person/valid/owner_asha.json"),
      json("person/valid/member_priya.json"),
    ]);
  });

  it("PPL_40a the Q4 meeting is the uploaded, minuted contract meeting, still to confirm", () => {
    const q4 = MEETINGS.find((m) => m.id === "mt_q4_plan");
    expect(q4).toEqual({
      ...(json("meeting/valid/upload_minuted.json") as object),
      minutes_confirmed_by: null,
    });
  });

  it("PPL_40a the manual item is shaped like the contract's manual item", () => {
    const manual = WORK_ITEMS.find((i) => i.id === "wi_call_acme");
    expect(Object.keys(manual ?? {}).sort()).toEqual(
      Object.keys(json("work_item/valid/manual_open.json") as object).sort(),
    );
  });
});
