// PPL-40b: the fixtures S-28 and S-29 read are the contracts/fixtures records they copy, or are
// derived from them (never invented shapes), and every one validates against its schema. The JSON
// and the schemas are read here, in the test only.
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020.js";
import { describe, expect, it } from "vitest";
import { AGENDA_ROWS, ALL_MEETINGS, CAL_ENTRIES, FREE_BUSY, MENTIONS, PINS } from "./data";

const root = fileURLToPath(new URL("../../../../contracts/", import.meta.url));
const json = (path: string): unknown => JSON.parse(readFileSync(`${root}fixtures/${path}`, "utf8"));
const ajv = new Ajv2020({ strict: false, allErrors: true, validateFormats: false });
for (const file of readdirSync(root, { recursive: true, encoding: "utf8" }))
  if (file.endsWith(".schema.json"))
    ajv.addSchema(JSON.parse(readFileSync(`${root}${file}`, "utf8")));
const schema = (name: string) => ajv.getSchema(`https://contracts.tilo.example/${name}`);

const byId = <T extends { id: string }>(xs: readonly T[], id: string): T | undefined =>
  xs.find((x) => x.id === id);

describe("PPL-40b fixtures stay the contract fixtures they copy", () => {
  it("FR-PB-01 four pins are the contract pins, record for record", () => {
    expect(byId(PINS, "pb_rate_sheet")).toEqual(
      json("pinboard_item/valid/team_active_confirmed.json"),
    );
    expect(byId(PINS, "pb_launch_date")).toEqual(
      json("pinboard_item/valid/team_entry_by_person.json"),
    );
    expect(byId(PINS, "pb_brief_link")).toEqual(json("pinboard_item/valid/team_link.json"));
    expect(byId(PINS, "pb_owner_followup")).toEqual(
      json("pinboard_item/valid/personal_added_by_tilo.json"),
    );
    expect(byId(PINS, "pb_priya_note")).toEqual(json("pinboard_item/valid/personal_note.json"));
  });

  it("FR-PB-04 the tags are the contract mentions, pointed at a pin of this board", () => {
    const tagged = json("mention/valid/priya_tagged.json") as object;
    expect(byId(MENTIONS, "mn_rate_priya")).toEqual({
      ...tagged,
      id: "mn_rate_priya",
      pin_id: "pb_rate_sheet",
    });
    const removed = json("mention/valid/priya_removed_herself.json") as object;
    expect(byId(MENTIONS, "mn_brief_priya")).toEqual({
      ...removed,
      id: "mn_brief_priya",
      pin_id: "pb_brief_link",
    });
  });

  it("FR-CAL-01 the entries are the contract entries: a teammate's own is untouched, the rest are the person's", () => {
    expect(byId(CAL_ENTRIES, "ce_dentist")).toEqual(json("calendar_entry/valid/manual_own.json"));
    const own = (name: string, extra: object) => ({
      ...(json(`calendar_entry/valid/${name}.json`) as object),
      owner: "u_owner",
      ...extra,
    });
    expect(byId(CAL_ENTRIES, "ce_budget_review")).toEqual(own("google_cached", {}));
    expect(byId(CAL_ENTRIES, "ce_launch_sync")?.share).toEqual({ team: "tm_launch" });
    expect(byId(CAL_ENTRIES, "ce_rate_prep")?.state).toBe("proposed");
    expect(byId(CAL_ENTRIES, "ce_followup_thu")?.confirmed_by?.by).toBe("u_owner");
  });

  it("FR-CAL-06 the teammate's free/busy keeps the contract view's busy interval and only intervals", () => {
    const view = json("calendar_entry.free_busy/valid/teammate_view.json") as {
      user: string;
      busy: unknown[];
    };
    expect(FREE_BUSY[0]?.user).toBe(view.user);
    expect(FREE_BUSY[0]?.busy[0]).toEqual(view.busy[0]);
    for (const b of FREE_BUSY.flatMap((f) => f.busy))
      expect(Object.keys(b).sort()).toEqual(["end", "start"]);
  });

  it("FR-CAL-01 every fixture the screens read validates against its schema", () => {
    const check = (name: string, records: readonly unknown[]) => {
      const valid = schema(name);
      expect(valid, name).toBeDefined();
      for (const r of records)
        expect(valid?.(r), `${name}: ${JSON.stringify(valid?.errors)}`).toBe(true);
    };
    check("pinboard_item.schema.json", PINS);
    check("mention.schema.json", MENTIONS);
    check("calendar_entry.schema.json", CAL_ENTRIES);
    check("calendar_entry.schema.json#/$defs/agenda_item", AGENDA_ROWS);
    check("calendar_entry.schema.json#/$defs/free_busy", FREE_BUSY);
    check("meeting.schema.json", ALL_MEETINGS);
  });

  it("FR-CAL-06 the check itself rejects free/busy that carries a title", () => {
    const valid = schema("calendar_entry.schema.json#/$defs/free_busy");
    const [fb] = FREE_BUSY;
    expect(valid?.({ ...fb, busy: [{ ...fb?.busy[0], title: "Dentist" }] })).toBe(false);
  });
});
