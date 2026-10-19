// The worlds of the sample company that only the Park pages know (their ids are `park/api/fixtures/worlds.ts`'s).
// The old stage and lens screens have one recorded run (the fixture world), so a deep link to a stage or lens of
// one of these has nothing to draw: `App` sends it to the world's Park page (WEB-QA-14OCT-1), where the lens links
// are shown disabled with their reason. Dependency-free on purpose (the entry chunk must not load the fixtures);
// `parkWorlds.test.ts` keeps it equal to the fixtures' list.
const PARK_ONLY: ReadonlySet<string> = new Set([
  "k1",
  "hires",
  "audit",
  "northline",
  "invoice",
  "inbox",
  "pricing",
  "calls",
  "venues",
  "comp",
  "reply",
]);

/** True when `worldId` is a sample-company world with a Park page and no recorded run for the old screens. */
export const isParkOnlyWorld = (worldId: string): boolean => PARK_ONLY.has(worldId);
