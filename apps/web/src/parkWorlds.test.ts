// WEB-QA-14OCT-1 (UI-10): the old stage and lens screens know one recorded run (the fixture world). A sample
// company's world that only the Park pages know (k1, hires, ...) has no run, so a deep link to its stage or a lens
// goes to its Park page, where those links are shown off with their reason, instead of a 404 in the old shell.
// The list is dependency-free (Root and App must not pull the fixtures into their chunks); this test keeps it
// equal to the Park fixtures' own world list.
import { describe, expect, it } from "vitest";
import { FIXTURE_WORLD_ID } from "./api/fixtures/derived";
import { worlds } from "./park/api/fixtures/worlds";
import { isParkOnlyWorld } from "./parkWorlds";

describe("WEB-QA-14OCT parkWorlds", () => {
  it("UI-10 WEB-QA-14OCT every Park fixture world is Park-only, and nothing else is", () => {
    for (const w of worlds()) expect(isParkOnlyWorld(w.id), w.id).toBe(true);
    expect(isParkOnlyWorld("k1")).toBe(true);
    expect(isParkOnlyWorld(FIXTURE_WORLD_ID)).toBe(false); // the old stage's own recorded run
    expect(isParkOnlyWorld("nope")).toBe(false); // an unknown id stays "Not found"
    expect(isParkOnlyWorld("new1")).toBe(false); // a world started on this device has no fixture
  });
});
