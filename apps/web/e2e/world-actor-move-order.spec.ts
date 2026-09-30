import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { DESKTOP } from "./support/viewports";
import { canvasSnapshot, fixtureUrl, stageCanvas, stageSeq } from "./support/world";

// P4 / HR-3 regression: "every location change for an actor goes through that actor's
// choreographer queue in seq order ..., and the settled canvas after playback is
// pixel-identical to /?fixture=X&seq=<last>."
//
// Reproduces the race a queue-bypassing write let through: actor A_l1's `agent.moved` (walking
// to B7) is still mid-flight in the choreographer when a second, same-actor event
// (`agent.working` at B12) lands less than its 600ms walk duration later. Applying that second
// event straight into agentPos (bypassing the queue) let the *first* move's completion later
// overwrite agentPos with its own (now-stale) destination, leaving the settled canvas showing
// B7 while data-seq, the trace and the reducer had all already moved the actor on to B12.
//
// Reuses apps/web/fixtures/crowd-20.{layout,events}.jsonl's own real, schema-valid content
// (apps/web/scripts/make-crowd-fixture.mjs / tests/web/test_FR_WLD_10_crowd_fixtures_valid.py)
// for everything up to its first two `agent.moved` events (seq 1..23, which spawns A_l1 at B1),
// then appends two synthetic events of the same shape under a `?fixture=attack` name that
// doesn't exist on disk, via page.route — no new fixture files needed.

const FIXTURES_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "../fixtures");
const CROWD_LAYOUT = fs.readFileSync(path.join(FIXTURES_DIR, "crowd-20.layout.json"), "utf8");
const CROWD_EVENTS = fs
  .readFileSync(path.join(FIXTURES_DIR, "crowd-20.events.jsonl"), "utf8")
  .split("\n")
  .filter((line) => line.trim().length > 0);

const BASE_EVENTS = CROWD_EVENTS.slice(0, 23); // seq 1..23: spawns everyone, A_l1 lands at B2
const lastBaseEventRaw = BASE_EVENTS.at(-1);
if (!lastBaseEventRaw) throw new Error("crowd-20.events.jsonl has fewer than 23 lines");
const LAST_TS = (JSON.parse(lastBaseEventRaw) as { ts: string }).ts;
const plusMs = (ms: number) => new Date(Date.parse(LAST_TS) + ms).toISOString();

// seq 24: A_l1 starts walking to B7 (a 600ms choreographed move, MOVE_DURATION_MS in runWorld.ts).
const MOVE_EVENT = JSON.stringify({
  v: "1.0",
  id: "00000000000000000000000AA",
  seq: 24,
  ts: plusMs(1000),
  world_id: "w_crowd_20",
  run_id: "r_crowd_20_1",
  type: "agent.moved",
  actor: "A_l1",
  target: "B7",
  level: "L1",
  district: "D2",
  item: null,
  severity: "info",
  credits: 0,
  summary: "A_l1 walked to B7.",
  cause: "0000000000000000000000000Q",
  vis: "all",
  authz: null,
  data: { from: "B2" },
  trace: {
    model_role: null,
    profile: null,
    tokens_in: null,
    tokens_out: null,
    tool: null,
    latency_ms: null,
    archive_ref: null,
  },
});

// seq 25: 200ms later — well inside seq 24's 600ms walk — A_l1 starts working at B12 instead.
const WORKING_EVENT = JSON.stringify({
  v: "1.0",
  id: "00000000000000000000000AB",
  seq: 25,
  ts: plusMs(1200),
  world_id: "w_crowd_20",
  run_id: "r_crowd_20_1",
  type: "agent.working",
  actor: "A_l1",
  target: "B12",
  level: "L1",
  district: "D3",
  item: null,
  severity: "info",
  credits: 0,
  summary: "A_l1 started working at B12.",
  cause: "00000000000000000000000AA",
  vis: "all",
  authz: null,
  data: { unit: null },
  trace: {
    model_role: null,
    profile: null,
    tokens_in: null,
    tokens_out: null,
    tool: null,
    latency_ms: null,
    archive_ref: null,
  },
});

const ATTACK_EVENTS = [...BASE_EVENTS, MOVE_EVENT, WORKING_EVENT].join("\n");
const LAST_SEQ = 25;

test.use({ viewport: DESKTOP });

test.beforeEach(async ({ page }) => {
  await page.route(/\/fixtures\/attack\.layout\.json/, (route) =>
    route.fulfill({ contentType: "application/json", body: CROWD_LAYOUT }),
  );
  await page.route(/\/fixtures\/attack\.events\.jsonl/, (route) =>
    route.fulfill({ contentType: "application/x-ndjson", body: ATTACK_EVENTS }),
  );
});

test("HR-3: a same-actor event that lands mid-walk never lets the finishing walk overwrite it — the settled canvas matches the final static frame", async ({
  page,
}) => {
  await page.goto(fixtureUrl("attack"));
  await expect(stageCanvas(page)).toBeVisible();
  await expect.poll(() => stageSeq(page), { timeout: 10_000 }).toBe(LAST_SEQ);

  // HR-3 caps any in-flight move at 2s (this stream's own move is 600ms); give it comfortable
  // room to fully settle before comparing pixels.
  await page.waitForTimeout(2_500);
  const played = await canvasSnapshot(page);

  await page.goto(fixtureUrl("attack", { seq: LAST_SEQ }));
  await expect(stageCanvas(page)).toBeVisible();
  await expect.poll(() => stageSeq(page)).toBe(LAST_SEQ);
  const staticLast = await canvasSnapshot(page);

  expect(
    played,
    `the settled canvas after playback must match the static frame at the final seq (${LAST_SEQ}) — a stale, already-superseded position means a queued move overwrote a later same-actor event`,
  ).toBe(staticLast);
});
