// PPL-40a: whatever the plate reducer does to a work item, the result is still a valid
// work_item.schema.json record (a history entry with an unknown change or status would not be).
// The schemas are read here, in the test only.
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";
import { WORK_ITEMS } from "./data";
import { type PlateAction, reducePlate } from "./plate";

const root = fileURLToPath(new URL("../../../../contracts/", import.meta.url));
const ajv = new Ajv2020({ strict: false, allErrors: true, validateFormats: false });
for (const file of readdirSync(root, { recursive: true, encoding: "utf8" }))
  if (file.endsWith(".schema.json"))
    ajv.addSchema(JSON.parse(readFileSync(`${root}${file}`, "utf8")));
const valid = ajv.getSchema("https://contracts.tilo.example/work_item.schema.json");

const KINDS: readonly PlateAction["kind"][] = ["done", "snooze", "not_mine", "put_back"];

describe("PPL-40a plate reducer output stays contract-valid", () => {
  it("PPL_40a the check itself rejects a history entry the contract does not know", () => {
    const [first] = WORK_ITEMS;
    const bad = {
      ...first,
      history: [{ at: "2026-10-07T04:00:00.000Z", by: "u_owner", change: "bogus", status: "open" }],
    };
    expect(valid?.(bad)).toBe(false);
  });

  it("PPL_40a every fixture item, and each action applied to it, validates against work_item.schema.json", () => {
    expect(valid).toBeDefined();
    for (const item of WORK_ITEMS) {
      expect(valid?.(item), `${item.id}: ${JSON.stringify(valid?.errors)}`).toBe(true);
      for (const kind of KINDS) {
        const next = reducePlate(WORK_ITEMS, { kind, id: item.id }).find((i) => i.id === item.id);
        expect(valid?.(next), `${item.id} after ${kind}: ${JSON.stringify(valid?.errors)}`).toBe(
          true,
        );
      }
    }
  });
});
