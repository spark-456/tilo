// WEB-1a (plan sections 2, 5, 6.1): the fixture Api serves the typed fixtures with `source: "fixture"`.
// Reads equal the fixtures; writes resolve to a typed acknowledgement with source "fixture"; decide and
// undo act on the instance's own copy of `dec`; shared fixture objects are never mutated; two instances
// share no state. Defaults chosen where the plan is silent are noted next to the test.
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEC_COMBOS, callTable, invoke } from "../../../test-support/park/apiCalls";
import { deepFreeze } from "../../../test-support/park/freeze";
import { createFixtureApi } from "./fixtureApi";
import * as fx from "./fixtures";
import { API_METHODS } from "./index";
import type { Dec, DecisionKey } from "./types";

// Every shared fixture object is frozen for this file: any write by the Api throws a TypeError.
for (const shared of [
  fx.user,
  fx.today,
  fx.decisions,
  fx.skills,
  fx.learn,
  fx.ledger,
  fx.agenda,
  fx.team,
  fx.connectors,
  fx.notifications,
  fx.TIERS,
  fx.LEVELS,
]) {
  deepFreeze(shared);
}

const snapshot = () =>
  JSON.stringify([
    fx.user,
    fx.today,
    fx.decisions,
    fx.skills,
    fx.learn,
    fx.ledger,
    fx.agenda,
    fx.team,
    fx.connectors,
    fx.notifications,
    fx.TIERS,
    fx.LEVELS,
  ]);

const active = (dec: Dec): string[] =>
  Object.entries(dec)
    .filter(([, on]) => on)
    .map(([k]) => k)
    .sort();

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WEB_1a_fixture_api: reads", () => {
  it("WEB_1a_fixture_api_every_read_is_the_fixture_with_source_fixture", async () => {
    const api = createFixtureApi();
    const added = [fx.makeWorld("routine", "Weekly invoice match", 1)];
    const reads: [string, { data: unknown; source: string }, unknown][] = [
      ["getUser", await api.getUser(), fx.user],
      ["getToday", await api.getToday(), fx.today],
      ["getDecisions", await api.getDecisions(), fx.decisions],
      ["getSkills", await api.getSkills(), fx.skills],
      ["getLearn", await api.getLearn(), fx.learn],
      ["getLedger", await api.getLedger(), fx.ledger],
      ["getAgenda", await api.getAgenda(), fx.agenda],
      ["getTeam", await api.getTeam(), fx.team],
      ["getConnectors", await api.getConnectors(), fx.connectors],
      ["getNotifications", await api.getNotifications(), fx.notifications],
      ["getTeamPolicy", await api.getTeamPolicy(), fx.teamPolicy],
      ["getConnectorTerms", await api.getConnectorTerms(), fx.connectorTerms],
      ["getProfileSettings", await api.getProfileSettings(), fx.profileSettings],
      ["getBuildHandoff", await api.getBuildHandoff(), fx.buildHandoffs],
    ];
    for (const dec of DEC_COMBOS) {
      reads.push(["getWorlds", await api.getWorlds(dec, []), fx.worlds(dec, [])]);
      reads.push(["getWorlds+added", await api.getWorlds(dec, added), fx.worlds(dec, added)]);
      reads.push(["getPlans", await api.getPlans(dec), fx.plans(dec)]);
    }
    expect(reads.length).toBe(14 + 3 * DEC_COMBOS.length);
    for (const [name, result, expected] of reads) {
      expect(result.source, `${name}.source`).toBe("fixture");
      expect(result.data, `${name}.data`).toEqual(expected);
      expect(Object.keys(result).sort(), `${name} result keys`).toEqual(["data", "source"]);
    }
  });

  it("WEB_1a_fixture_api_reads_do_not_hand_out_the_shared_objects_for_writing", async () => {
    // Either a copy or a frozen object is fine; what must not happen is a caller changing the fixture.
    const api = createFixtureApi();
    const before = snapshot();
    const skills = (await api.getSkills()).data;
    const user = (await api.getUser()).data;
    try {
      const firstSkill = (skills as { name: string }[])[0];
      if (firstSkill) firstSkill.name = "changed by a caller";
    } catch {
      // frozen: good
    }
    try {
      (user as { name: string }).name = "changed by a caller";
    } catch {
      // frozen: good
    }
    expect(snapshot()).toBe(before);
    expect((await createFixtureApi().getUser()).data).toEqual(fx.user);
  });

  it("WEB_1a_fixture_api_resolves_asynchronously_and_makes_no_network_request", async () => {
    const fetchSpy = vi.fn(async () => {
      throw new Error("WEB-1a: the fixture api must not touch the network");
    });
    vi.stubGlobal("fetch", fetchSpy);
    const api = createFixtureApi();
    const args = callTable();
    for (const m of API_METHODS) {
      const p = invoke(api, m, args);
      expect(p, `${m} returns a Promise`).toBeInstanceOf(Promise);
      await p;
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("WEB_1a_fixture_api: writes", () => {
  it("WEB_1a_fixture_api_every_write_resolves_with_a_typed_ack_and_source_fixture", async () => {
    const api = createFixtureApi();
    const before = snapshot();
    const t = callTable();
    const results = [
      await api.decide(...t.decide),
      await api.undo(...t.undo),
      await api.startWorld(...t.startWorld),
      await api.saveSkill(...t.saveSkill),
      await api.setToolLevel(...t.setToolLevel),
      await api.bookSlot(...t.bookSlot),
      await api.addBackup(...t.addBackup),
      await api.setPref(...t.setPref),
    ];
    for (const r of results) {
      expect(r.source).toBe("fixture");
      expect(r.data.ok).toBe(true);
    }
    // No write touched a shared fixture (they are frozen here, so a write would also have thrown).
    expect(snapshot()).toBe(before);
    // Reads after the writes still equal the fixtures.
    expect((await api.getSkills()).data).toEqual(fx.skills);
    expect((await api.getAgenda()).data).toEqual(fx.agenda);
    expect((await api.getTeam()).data).toEqual(fx.team);
    expect((await api.getDecisions()).data).toEqual(fx.decisions);
  });

  it("WEB_1a_fixture_api_decide_is_idempotent_and_undo_restores", async () => {
    const api = createFixtureApi();
    const first = await api.decide("depot");
    expect(active(first.data.dec)).toEqual(["depot"]);
    expect((await api.decide("depot")).data.dec).toEqual(first.data.dec);

    const both = await api.decide("mail");
    expect(active(both.data.dec)).toEqual(["depot", "mail"]);
    expect(fx.needsLeft(both.data.dec)).toBe(0);

    const undone = await api.undo("depot");
    expect(active(undone.data.dec)).toEqual(["mail"]);
    expect(fx.needsLeft(undone.data.dec)).toBe(1);
    expect((await api.undo("depot")).data.dec).toEqual(undone.data.dec);

    const none = await api.undo("mail");
    expect(active(none.data.dec)).toEqual([]);
    expect(fx.needsLeft(none.data.dec)).toBe(2);
  });

  it("WEB_1a_fixture_api_undo_before_decide_changes_nothing", async () => {
    const api = createFixtureApi();
    expect(active((await api.undo("mail")).data.dec)).toEqual([]);
    expect(active((await api.decide("depot")).data.dec)).toEqual(["depot"]);
  });

  it("WEB_1a_fixture_api_a_caller_changing_the_returned_dec_does_not_change_the_instance", async () => {
    const api = createFixtureApi();
    const first = await api.decide("depot");
    try {
      (first.data.dec as Record<string, boolean>).depot = false;
      (first.data.dec as Record<string, boolean>).mail = true;
    } catch {
      // frozen: good
    }
    expect(active((await api.decide("mail")).data.dec)).toEqual(["depot", "mail"]);
  });

  it("WEB_1a_fixture_api_two_instances_do_not_share_state", async () => {
    const a = createFixtureApi();
    const b = createFixtureApi();
    await a.decide("depot");
    expect(active((await b.decide("mail")).data.dec)).toEqual(["mail"]);
    expect(active((await a.undo("mail")).data.dec)).toEqual(["depot"]);
    // started worlds count per instance (the prototype's id is "new" + (added.length + 1))
    expect((await a.startWorld("quick", "x")).data.world.id).toBe("new1");
    expect((await a.startWorld("quick", "y")).data.world.id).toBe("new2");
    expect((await b.startWorld("quick", "z")).data.world.id).toBe("new1");
  });

  it("WEB_1a_fixture_api_startWorld_returns_the_prototype_world", async () => {
    // Default (plan section 5, README addWorld): the world is makeWorld(mode, query, startedSoFar + 1).
    const api = createFixtureApi();
    const one = await api.startWorld("workspace", "Plan the offsite");
    expect(one.source).toBe("fixture");
    expect(one.data.world).toEqual(fx.makeWorld("workspace", "Plan the offsite", 1));
    const two = await api.startWorld("routine", "");
    expect(two.data.world).toEqual(fx.makeWorld("routine", "", 2));
    expect(two.data.world.tier).toBe("Town");
  });

  it("WEB_1a_fixture_api_property_decide_undo_follow_a_set_model", async () => {
    const op = fc.tuple(
      fc.constantFrom("decide", "undo"),
      fc.constantFrom<DecisionKey>("depot", "mail"),
    );
    await fc.assert(
      fc.asyncProperty(fc.array(op, { maxLength: 25 }), fc.boolean(), async (ops, twice) => {
        const api = createFixtureApi();
        const model = new Set<string>();
        for (const [kind, key] of ops) {
          if (kind === "decide") model.add(key);
          else model.delete(key);
          let got = (await api[kind](key)).data.dec;
          if (twice) got = (await api[kind](key)).data.dec; // repeating a call changes nothing
          expect(active(got)).toEqual([...model].sort());
          expect(fx.needsLeft(got)).toBe(2 - model.size);
        }
      }),
      { numRuns: 60 },
    );
  });
});
