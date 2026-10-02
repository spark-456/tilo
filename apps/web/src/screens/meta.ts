// PRD 18.3 screen list: the one table that says which screens exist. Names, priorities and
// pillars are the PRD's. `status` is what the /screens index and the "Coming soon" stubs report:
// flip a row to "built" in the same change that replaces its S_NN.tsx stub body (AGW-08).
// `pattern` is the router's match for screens outside the flow shell (FlowShell.tsx owns S-01 to
// S-04, with the stage); `path` is a concrete address for links, using the fixture ids (HR-4).
import { FIXTURE_TASK_ID, FIXTURE_WORLD_ID } from "../api/fixtures/derived";

export type ScreenStatus = "built" | "placeholder" | "deferred";

export interface ScreenMeta {
  readonly id: string;
  readonly name: string;
  readonly priority: "Must" | "Should";
  readonly pillar: string;
  readonly status: ScreenStatus;
  /** A concrete address for links, or null while a Should screen is not scheduled. */
  readonly path: string | null;
  /** Set for every screen the router resolves itself (all but the flow-shell screens). */
  readonly pattern?: RegExp;
}

const W = `/world/${FIXTURE_WORLD_ID}`;
const T = `/task/${FIXTURE_TASK_ID}`;

const must = (
  id: string,
  name: string,
  pillar: string,
  path: string,
  pattern?: RegExp,
): ScreenMeta => ({
  id,
  name,
  pillar,
  path,
  status: "placeholder",
  priority: "Must",
  ...(pattern ? { pattern } : {}),
});
/** Flip a row to built in the change that replaces its stub (AGW-08). */
const built = (m: ScreenMeta): ScreenMeta => ({ ...m, status: "built" });
const later = (id: string, name: string, pillar: string): ScreenMeta => ({
  id,
  name,
  pillar,
  path: null,
  status: "deferred",
  priority: "Should",
});

export const SCREENS: readonly ScreenMeta[] = [
  must("S-01", "Start", "P1", "/"),
  must("S-02", "Understanding", "P1", `${T}/understanding`),
  must("S-03", "Approaches and budget", "P1", `${T}/approaches`),
  built(must("S-04", "World with HUD", "P3", W)),
  built(
    must(
      "S-05",
      "Inspect panel",
      "P3",
      `${W}/inspect/B1`,
      /^\/world\/([^/]+)\/inspect\/([^/]+)\/?$/,
    ),
  ),
  must("S-06", "Needs-you queue and card", "P4", "/needs-you", /^\/needs-you\/?$/),
  must("S-07", "Gate sheet", "P4", "/needs-you/gate", /^\/needs-you\/gate\/?$/),
  must("S-08", "Connection consent sheet", "P6", "/needs-you/consent", /^\/needs-you\/consent\/?$/),
  must("S-09", "Meeting", "P2", "/meeting", /^\/meeting\/?$/),
  built(must("S-10", "Story lens", "P3", `${W}/story`, /^\/world\/([^/]+)\/story\/?$/)),
  built(must("S-11", "Trace lens", "P3, P7", `${W}/trace`, /^\/world\/([^/]+)\/trace\/?$/)),
  built(
    must(
      "S-12",
      "Delivery and celebration",
      "P6, P8",
      `${W}/delivery`,
      /^\/world\/([^/]+)\/delivery\/?$/,
    ),
  ),
  built(must("S-13", "Library and Memory Vault", "P7", "/library", /^\/library\/?$/)),
  built(must("S-14", "Worlds list and replays", "P3", "/worlds", /^\/worlds\/?$/)),
  built(must("S-15", "Autonomy", "P4", "/autonomy", /^\/autonomy\/?$/)),
  built(must("S-16", "Channels", "P5", "/channels", /^\/channels\/?$/)),
  built(must("S-17", "Email Autopilot home", "P5", "/mail", /^\/mail\/?$/)),
  built(must("S-18", "Team Lead console", "P4", "/team", /^\/team\/?$/)),
  built(must("S-19", "Connections", "P6", "/connections", /^\/connections\/?$/)),
  later("S-20", "Skills library", "P2"),
  built(
    must(
      "S-21",
      "Artifact history and restore",
      "P7",
      "/library/artifacts",
      /^\/library\/artifacts\/?$/,
    ),
  ),
  built(must("S-22", "Settings", "P7", "/settings", /^\/settings\/?$/)),
  built(must("S-23", "How we estimate; status page", "P8", "/estimate", /^\/estimate\/?$/)),
  built(must("S-24", "Pilot diary and survey", "P8", "/pilot", /^\/pilot\/?$/)),
  later("S-25", "Stage mode overlay", "P3"),
];

export const screenMeta = (id: string): ScreenMeta | undefined => SCREENS.find((s) => s.id === id);
