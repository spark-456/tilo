// Generates a synthetic "crowd" WorldLayout + event stream for the FR-WLD-10 / BQ-08 perf
// proxy test (ticket P0-08b-player): apps/web/e2e/world-perf.spec.ts loads it via
// `?fixture=crowd-<N>` and measures rAF frame times with CPU throttling while N agents move.
//
// Usage: node scripts/make-crowd-fixture.mjs <agentCount>   (defaults to 20)
// Writes apps/web/fixtures/crowd-<agentCount>.layout.json and
// apps/web/fixtures/crowd-<agentCount>.events.jsonl.
//
// Deterministic and seeded (mulberry32, SEED below): the same agentCount always produces byte-
// identical output, which is what tests/web/test_FR_WLD_10_crowd_fixtures_valid.py checks
// against contracts/layout.schema.json, contracts/event.schema.json and the per-type data
// schemas in contracts/events/data/.
//
// Layout shape: one level, up to 6 districts (PRD 9.1), each with a lead and up to 5 common
// buildings (PRD 9.1). One director plus (agentCount - 1) leads/specialists, all of whom walk
// (agent.moved) between their district's buildings for the whole stream, so the perf test has a
// continuous crowd to measure. No islands/gates/bridges: this fixture exists to stress movement
// rendering, not connectors or approvals.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SEED = 1337;
const MOVES_PER_AGENT = 10;
const EVENT_GAP_MS = 100;
const BUILDINGS_PER_DISTRICT = 5;
const MAX_DISTRICTS = 6;

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function tierFor(agentCount) {
  if (agentCount <= 2) return "outpost";
  if (agentCount <= 6) return "village";
  if (agentCount <= 15) return "town";
  return "city";
}

const COMMON_TYPES = [
  "town_hall",
  "your_desk",
  "library",
  "browser_station",
  "workshop",
  "meeting_hall",
  "connector_post",
  "memory_vault",
  "treasury",
  "watchtower",
  "delivery_dock",
  "clock_tower",
  "agent_foundry",
  "mail_room",
  "expert_office",
];

// Crockford base32 (ULID alphabet), first char restricted to 0-7 as common.schema.json requires.
const ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
function toUlid(index) {
  let n = index >>> 0;
  let body = "";
  for (let i = 0; i < 25; i++) {
    body = ULID_ALPHABET[n % 32] + body;
    n = Math.floor(n / 32);
  }
  return `0${body}`; // 26 chars total; leading "0" satisfies the [0-7] first-char rule
}

function buildLayout(agentCount, rng) {
  const remaining = agentCount - 1; // everyone but the director
  const numDistricts = Math.max(1, Math.min(MAX_DISTRICTS, Math.ceil(remaining / 5)));

  const agents = [{ id: "A_dir", rank: "director" }];
  const districts = [];
  const geometryDistricts = [];
  const geometryBuildings = [];
  const movers = []; // { agentId, districtId, buildingIds: string[] }

  let buildingCounter = 1;
  let moverIndex = 0;
  const perDistrict = Math.ceil(remaining / numDistricts);

  for (let d = 0; d < numDistricts; d++) {
    const districtId = `D${d + 1}`;
    const leadId = `A_l${d + 1}`;
    agents.push({ id: leadId, rank: "lead" });

    const buildingIds = [];
    for (let b = 0; b < BUILDINGS_PER_DISTRICT; b++) {
      const buildingId = `B${buildingCounter}`;
      buildingCounter++;
      buildingIds.push(buildingId);
      geometryBuildings.push({
        id: buildingId,
        footprint: { x: 1 + b * 3, y: 1 + d * 4, w: 2, d: 2 },
        floors: 1,
      });
    }

    const semanticBuildings = buildingIds.map((id, i) => ({
      id,
      name: `Crowd Bay ${d + 1}.${i + 1}`,
      kind: "common",
      common_type: COMMON_TYPES[(d * BUILDINGS_PER_DISTRICT + i) % COMMON_TYPES.length],
      plan_units: [],
    }));

    districts.push({
      id: districtId,
      name: `Crowd District ${d + 1}`,
      icon: "workshop",
      lead: leadId,
      buildings: semanticBuildings,
    });
    geometryDistricts.push({
      id: districtId,
      plot: { x: 0, y: d * 4, w: BUILDINGS_PER_DISTRICT * 3 + 1, d: 3 },
      tint: `district.${(d % 6) + 1}`,
    });

    movers.push({ districtId, leadId, buildingIds, specialists: [] });
  }

  for (let i = 0; i < remaining - numDistricts; i++) {
    const districtIndex = moverIndex % numDistricts;
    moverIndex++;
    const specialistId = `A_s${i + 1}`;
    agents.push({ id: specialistId, rank: "specialist" });
    movers[districtIndex].specialists.push(specialistId);
  }

  const layout = {
    v: "1.0",
    world_id: `w_crowd_${agentCount}`,
    tier: tierFor(agentCount),
    theme: "metropolis",
    semantic: {
      levels: [{ id: "L1", name: "Crowd Floor", districts }],
      islands: [],
      gates: [],
      agents,
    },
    geometry: {
      solver_version: "1.0.0",
      levels: [
        {
          id: "L1",
          index: 0,
          plate: { x: 0, y: 0, w: BUILDINGS_PER_DISTRICT * 3 + 2, d: numDistricts * 4 + 1 },
        },
      ],
      districts: geometryDistricts,
      buildings: geometryBuildings,
      islands: [],
      roads: [],
      bridges: [],
      gates: [],
    },
  };

  // Every mover (lead + specialists) walks between its district's buildings.
  const moveList = [];
  for (const district of movers) {
    for (const agentId of [district.leadId, ...district.specialists]) {
      moveList.push({
        agentId,
        districtId: district.districtId,
        buildingIds: district.buildingIds,
      });
    }
  }
  // Deterministic shuffle (seeded) so movers interleave rather than walking district by district.
  for (let i = moveList.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [moveList[i], moveList[j]] = [moveList[j], moveList[i]];
  }

  return { layout, moveList };
}

function buildEvents(agentCount, layout, moveList) {
  const events = [];
  let seq = 1;
  let tMs = 0;
  const baseTs = Date.UTC(2026, 8, 29, 9, 0, 0);
  const worldId = layout.world_id;
  const runId = `r_crowd_${agentCount}_1`;

  const traceNull = {
    model_role: null,
    profile: null,
    tokens_in: null,
    tokens_out: null,
    tool: null,
    latency_ms: null,
    archive_ref: null,
  };

  function push(type, actor, target, level, district, summary, data) {
    events.push({
      v: "1.0",
      id: toUlid(seq),
      seq,
      ts: new Date(baseTs + tMs).toISOString(),
      world_id: worldId,
      run_id: runId,
      type,
      actor,
      target,
      level,
      district,
      item: null,
      severity: "info",
      credits: 0,
      summary: summary.slice(0, 140),
      cause: seq > 1 ? toUlid(seq - 1) : null,
      vis: "all",
      authz: null,
      data,
      trace: traceNull,
    });
    seq++;
  }

  push("world.requested", "u_owner", worldId, null, null, "Simulate a crowd for the perf test.", {
    title: "Crowd perf fixture",
    channel: "web",
    destination: null,
  });
  push("world.started", "A_dir", worldId, null, null, "Work started with a budget of 0 credits.", {
    budget_cap: 0,
  });
  for (const agent of layout.semantic.agents) {
    push("agent.spawned", "A_dir", agent.id, "L1", null, `A ${agent.rank} joined the crowd.`, {
      role: agent.rank,
    });
  }

  // Round-robin the movers' moves so many agents animate at once (P9: "20 agents all moving
  // throughout"), each agent alternating between its district's buildings.
  const cursors = new Map(moveList.map((m) => [m.agentId, 0]));
  tMs += EVENT_GAP_MS;
  for (let round = 0; round < MOVES_PER_AGENT; round++) {
    for (const mover of moveList) {
      const buildings = mover.buildingIds;
      const from = buildings[cursors.get(mover.agentId) % buildings.length];
      const nextIndex = cursors.get(mover.agentId) + 1;
      cursors.set(mover.agentId, nextIndex);
      const to = buildings[nextIndex % buildings.length];
      push(
        "agent.moved",
        mover.agentId,
        to,
        "L1",
        mover.districtId,
        `${mover.agentId} walked to ${to}.`,
        { from },
      );
      tMs += EVENT_GAP_MS;
    }
  }

  push("world.completed", "A_dir", worldId, null, null, "Crowd perf fixture finished.", {
    credits_used: 0,
    deliverable_count: 0,
  });

  return events;
}

function main() {
  const agentCount = Number.parseInt(process.argv[2] ?? "20", 10);
  if (!Number.isInteger(agentCount) || agentCount < 1) {
    console.error("Usage: node scripts/make-crowd-fixture.mjs <agentCount>");
    process.exit(1);
  }

  const rng = mulberry32(SEED);
  const { layout, moveList } = buildLayout(agentCount, rng);
  const events = buildEvents(agentCount, layout, moveList);

  const __dirname = path.dirname(fileURLToPath(import.meta.url));
  const outDir = path.resolve(__dirname, "..", "fixtures");
  fs.mkdirSync(outDir, { recursive: true });

  const layoutPath = path.join(outDir, `crowd-${agentCount}.layout.json`);
  const eventsPath = path.join(outDir, `crowd-${agentCount}.events.jsonl`);
  fs.writeFileSync(layoutPath, `${JSON.stringify(layout, null, 2)}\n`, "utf-8");
  fs.writeFileSync(eventsPath, `${events.map((e) => JSON.stringify(e)).join("\n")}\n`, "utf-8");

  console.log(`Wrote ${layoutPath} (${layout.semantic.agents.length} agents)`);
  console.log(`Wrote ${eventsPath} (${events.length} events)`);
}

main();
