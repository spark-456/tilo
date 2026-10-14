// WEB-CUTOVER: /world/:id is the Park World overview now, so no in-app link may build the bare
// `/world/${id}` address for the live stage. Each of these files must go through `stagePath(...)` from
// src/router.ts. The scan is on source text: it flags a template literal `/world/${...}` that is not
// followed by /story, /trace, /delivery or /inspect (those lens links keep their addresses).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = resolve(__dirname, "..");

// Link to the stage: LensTabs World tab, PrimaryNav world item, S-03 after approval, S-05 back link,
// S-12 "Back to the world", the Park World page's "Open live stage" link.
const FILES = [
  "screens/LensTabs.tsx",
  "screens/PrimaryNav.tsx",
  "screens/S_05.tsx",
  "screens/S_12.tsx",
  "screens/S_14.tsx", // the replays list: its "World" pill
  "park/pages/World/WorldPage.tsx",
] as const;

const read = (rel: string): string => readFileSync(resolve(SRC, rel), "utf8");

/** `/world/${...}` or "/world/" + id, not followed by one of the lens suffixes. */
const BARE_WORLD_ADDRESS =
  /\/world\/\$\{[^}]*\}(?!\/(?:story|trace|delivery|inspect)\b)|\/world\/["'`]\s*\+/g;

describe("WEB_CUTOVER_stagePath: links to the live stage", () => {
  for (const rel of FILES) {
    it(`WEB_CUTOVER_04_${rel.replace(/[^A-Za-z0-9]+/g, "_")}_builds_no_bare_world_address`, () => {
      const text = read(rel);
      expect([...text.matchAll(BARE_WORLD_ADDRESS)].map((m) => m[0])).toEqual([]);
    });

    it(`WEB_CUTOVER_04_${rel.replace(/[^A-Za-z0-9]+/g, "_")}_uses_stagePath`, () => {
      expect(read(rel)).toMatch(/\bstagePath\(/);
    });
  }

  it("WEB_CUTOVER_04_the_scan_leaves_lens_links_alone", () => {
    const lens = [
      "`/world/${id}/story`",
      "`/world/${encodeURIComponent(worldId)}/trace`",
      "`/world/${id}/delivery`",
      "`/world/${id}/inspect/${B}`",
    ];
    for (const s of lens) expect(s.match(BARE_WORLD_ADDRESS), s).toBeNull();
    expect("`/world/${id}`".match(BARE_WORLD_ADDRESS)).not.toBeNull();
    expect(
      "`/world/${encodeURIComponent(worldId)}${suffix}`".match(BARE_WORLD_ADDRESS),
    ).not.toBeNull();
  });
});
