// Test-only helper for FR-WLD-07: a world.* event built from its contract fixture in
// contracts/fixtures/events/valid, so it carries every required field; a test names only the seq.
import fs from "node:fs";
import path from "node:path";
import type { Event } from "@tilo/contracts";
import { CONTRACTS_DIR } from "./worldFixtures";

export function fixtureEvent(name: string, seq: number): Event {
  const base = JSON.parse(
    fs.readFileSync(path.join(CONTRACTS_DIR, "fixtures", "events", "valid", `${name}.json`), "utf8"),
  ) as Event;
  return { ...base, seq, id: `01JB5VQ00000000000000088${String(seq).padStart(2, "0")}` };
}
