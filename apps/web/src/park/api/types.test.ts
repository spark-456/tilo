// WEB-1a (plan section 5; README "State and data"): typed shapes for every fixture in tilo-app.js.
// The checks below are type-level (expectTypeOf); they are enforced by `pnpm --filter @tilo/web run
// typecheck` and by src/park/typecheck.test.ts, which runs the compiler over every park file.
import { describe, expect, expectTypeOf, it } from "vitest";
import * as fx from "./fixtures";
import type { Api, ApiMethod } from "./index";
import type {
  Ack,
  Agenda,
  AgendaSlot,
  ApiResult,
  Connector,
  Dec,
  DecideAck,
  Decision,
  DecisionFacts,
  DecisionKey,
  Learn,
  Ledger,
  Notification,
  Plan,
  Skill,
  Source,
  StartAck,
  Team,
  Tier,
  TierKey,
  Today,
  User,
  World,
} from "./types";

describe("WEB_1a_types: the result envelope", () => {
  it("WEB_1a_types_source_and_result", () => {
    expectTypeOf<Source>().toEqualTypeOf<"fixture" | "live">();
    expectTypeOf<ApiResult<User>>().toEqualTypeOf<{ data: User; source: Source }>();
    expectTypeOf<ApiResult<number[]>["data"]>().toEqualTypeOf<number[]>();
  });

  it("WEB_1a_types_decision_key_and_dec", () => {
    expectTypeOf<DecisionKey>().toEqualTypeOf<"depot" | "mail">();
    expectTypeOf<TierKey>().toEqualTypeOf<"quick" | "routine" | "workspace">();
    // A full record, and an empty object, are both a valid `dec` (the prototype tolerates missing keys).
    expectTypeOf<Record<DecisionKey, boolean>>().toExtend<Dec>();
    expectTypeOf<Record<string, never>>().toExtend<Dec>();
  });
});

describe("WEB_1a_types: entity shapes follow the README data model", () => {
  it("WEB_1a_types_exact_keys_of_the_simple_entities", () => {
    expectTypeOf<keyof User>().toEqualTypeOf<
      "first" | "name" | "initials" | "email" | "title" | "org" | "plan" | "tz" | "lang" | "hours"
    >();
    expectTypeOf<keyof Today>().toEqualTypeOf<"long" | "short" | "time">();
    expectTypeOf<keyof Tier>().toEqualTypeOf<
      "tier" | "tool" | "word" | "agents" | "cost" | "eta" | "ph" | "start" | "hint" | "chips"
    >();
    expectTypeOf<keyof Learn>().toEqualTypeOf<"rates" | "reviews" | "helpers" | "tools">();
    expectTypeOf<keyof Team>().toEqualTypeOf<
      "people" | "rules" | "matrix" | "roles" | "coverage"
    >();
    expectTypeOf<keyof Ledger>().toEqualTypeOf<
      | "budget"
      | "spent"
      | "forecast"
      | "daily"
      | "by"
      | "tx"
      | "runs"
      | "waits"
      | "memory"
      | "hours"
      | "activity"
    >();
    expectTypeOf<keyof Agenda>().toEqualTypeOf<
      | "days"
      | "wkend"
      | "today"
      | "start"
      | "end"
      | "now"
      | "events"
      | "slots"
      | "details"
      | "pins"
      | "rules" // additive (WEB-9c), not in the prototype
    >();
  });

  it("WEB_1a_types_decision_shape", () => {
    expectTypeOf<Decision>().toEqualTypeOf<{
      k: DecisionKey;
      world: string;
      title: string;
      body: string;
      yes: string;
      icon: string;
      done: string;
      // additive designed copy (WEB-3b): the shell reads the toast and the approved title from the Api
      toast: string;
      approvedTitle: string;
      facts?: DecisionFacts; // additive (WEB-9c), not in the prototype
    }>();
  });

  it("WEB_1a_types_world_skill_connector_notification", () => {
    expectTypeOf<World["id"]>().toEqualTypeOf<string>();
    expectTypeOf<World["tier"]>().toEqualTypeOf<"Village" | "Town" | "City">();
    expectTypeOf<"needs" | "running" | "finished" | "scheduled">().toExtend<World["st"]>();
    // The optional parts of a World are typed (a quick task has no districts).
    for (const key of ["districts", "activity", "runs", "row", "single", "plan"] as const) {
      expectTypeOf<World>().toHaveProperty(key);
    }
    for (const key of [
      "id",
      "name",
      "tools",
      "used",
      "steps",
      "runs",
      "rate",
      "status",
      "st",
    ] as const) {
      expectTypeOf<Skill>().toHaveProperty(key);
    }
    expectTypeOf<Skill["rate"]>().toEqualTypeOf<number | null>();
    expectTypeOf<Skill["tools"]>().toExtend<ReadonlyArray<readonly [string, number]>>();
    expectTypeOf<Skill["used"]>().toExtend<readonly string[]>();
    for (const key of ["id", "name", "cat", "mono", "col", "st"] as const) {
      expectTypeOf<Connector>().toHaveProperty(key);
    }
    for (const key of ["id", "t", "title", "sub", "kind", "go"] as const) {
      expectTypeOf<Notification>().toHaveProperty(key);
    }
    expectTypeOf<Plan>().toHaveProperty("districts");
    expectTypeOf<Plan>().toHaveProperty("agents");
    expectTypeOf<AgendaSlot>().toEqualTypeOf<Agenda["slots"][number]>();
  });

  it("WEB_1a_types_acks", () => {
    expectTypeOf<Ack["ok"]>().toEqualTypeOf<true>();
    expectTypeOf<DecideAck>().toExtend<Ack>();
    expectTypeOf<DecideAck["dec"]>().toEqualTypeOf<Dec>();
    expectTypeOf<StartAck>().toExtend<Ack>();
    expectTypeOf<StartAck["world"]>().toEqualTypeOf<World>();
  });
});

describe("WEB_1a_types: the fixtures satisfy the types", () => {
  it("WEB_1a_types_fixtures_satisfy_types", () => {
    expectTypeOf(fx.user).toExtend<User>();
    expectTypeOf(fx.today).toExtend<Today>();
    expectTypeOf(fx.decisions).toExtend<readonly Decision[]>();
    expectTypeOf(fx.worlds({}, [])).toExtend<readonly World[]>();
    expectTypeOf(fx.plans({})).toExtend<Readonly<Record<string, Plan>>>();
    expectTypeOf(fx.skills).toExtend<readonly Skill[]>();
    expectTypeOf(fx.learn).toExtend<Learn>();
    expectTypeOf(fx.ledger).toExtend<Ledger>();
    expectTypeOf(fx.agenda).toExtend<Agenda>();
    expectTypeOf(fx.team).toExtend<Team>();
    expectTypeOf(fx.connectors).toExtend<readonly Connector[]>();
    expectTypeOf(fx.notifications).toExtend<readonly Notification[]>();
    expectTypeOf(fx.TIERS).toExtend<Readonly<Record<TierKey, Tier>>>();
    expectTypeOf(fx.makeWorld).returns.toExtend<World>();
    expectTypeOf(fx.needsLeft).returns.toEqualTypeOf<number>();
    expectTypeOf(fx.gbp).toEqualTypeOf<(v: number) => string>();
    // and at runtime, so the test is not an empty body
    expect(Object.keys(fx.TIERS)).toEqual(["quick", "routine", "workspace"]);
  });
});

// Each method returns a Promise of the typed envelope; a readonly array in the builder's signature is fine.
type R<T> = Promise<ApiResult<T>>;

describe("WEB_1a_types: the Api interface returns typed envelopes", () => {
  it("WEB_1a_types_api_reads", () => {
    expectTypeOf<ReturnType<Api["getUser"]>>().toEqualTypeOf<R<User>>();
    expectTypeOf<ReturnType<Api["getToday"]>>().toEqualTypeOf<R<Today>>();
    expectTypeOf<ReturnType<Api["getDecisions"]>>().toExtend<R<readonly Decision[]>>();
    expectTypeOf<ReturnType<Api["getWorlds"]>>().toExtend<R<readonly World[]>>();
    expectTypeOf<[Dec, World[]]>().toExtend<Parameters<Api["getWorlds"]>>();
    expectTypeOf<ReturnType<Api["getPlans"]>>().toExtend<R<Readonly<Record<string, Plan>>>>();
    expectTypeOf<[Dec]>().toExtend<Parameters<Api["getPlans"]>>();
    expectTypeOf<ReturnType<Api["getSkills"]>>().toExtend<R<readonly Skill[]>>();
    expectTypeOf<ReturnType<Api["getLearn"]>>().toEqualTypeOf<R<Learn>>();
    expectTypeOf<ReturnType<Api["getLedger"]>>().toEqualTypeOf<R<Ledger>>();
    expectTypeOf<ReturnType<Api["getAgenda"]>>().toEqualTypeOf<R<Agenda>>();
    expectTypeOf<ReturnType<Api["getTeam"]>>().toEqualTypeOf<R<Team>>();
    expectTypeOf<ReturnType<Api["getConnectors"]>>().toExtend<R<readonly Connector[]>>();
    expectTypeOf<ReturnType<Api["getNotifications"]>>().toExtend<R<readonly Notification[]>>();
    // reads without arguments take none
    expectTypeOf<Parameters<Api["getUser"]>>().toEqualTypeOf<[]>();
    expectTypeOf<Parameters<Api["getSkills"]>>().toEqualTypeOf<[]>();
  });

  it("WEB_1a_types_api_writes", () => {
    expectTypeOf<Parameters<Api["decide"]>>().toEqualTypeOf<[key: DecisionKey]>();
    expectTypeOf<ReturnType<Api["decide"]>>().toEqualTypeOf<R<DecideAck>>();
    expectTypeOf<Parameters<Api["undo"]>>().toEqualTypeOf<[key: DecisionKey]>();
    expectTypeOf<ReturnType<Api["undo"]>>().toEqualTypeOf<R<DecideAck>>();
    expectTypeOf<Parameters<Api["startWorld"]>>().toEqualTypeOf<[mode: TierKey, query: string]>();
    expectTypeOf<ReturnType<Api["startWorld"]>>().toEqualTypeOf<R<StartAck>>();
    expectTypeOf<Parameters<Api["saveSkill"]>>().toEqualTypeOf<[skill: Skill]>();
    expectTypeOf<ReturnType<Api["saveSkill"]>>().toEqualTypeOf<R<Ack>>();
    expectTypeOf<Parameters<Api["setToolLevel"]>>().toEqualTypeOf<[tool: string, level: number]>();
    expectTypeOf<ReturnType<Api["setToolLevel"]>>().toEqualTypeOf<R<Ack>>();
    expectTypeOf<Parameters<Api["bookSlot"]>>().toEqualTypeOf<[slot: AgendaSlot]>();
    expectTypeOf<ReturnType<Api["bookSlot"]>>().toEqualTypeOf<R<Ack>>();
    expectTypeOf<Parameters<Api["addBackup"]>>().toEqualTypeOf<[personId: string]>();
    expectTypeOf<ReturnType<Api["addBackup"]>>().toEqualTypeOf<R<Ack>>();
    expectTypeOf<Parameters<Api["setPref"]>>().toEqualTypeOf<[key: string, value: unknown]>();
    expectTypeOf<ReturnType<Api["setPref"]>>().toEqualTypeOf<R<Ack>>();
  });

  it("WEB_1a_types_api_method_names_are_the_keys_of_Api", () => {
    expectTypeOf<keyof Api>().toEqualTypeOf<ApiMethod>();
  });
});
