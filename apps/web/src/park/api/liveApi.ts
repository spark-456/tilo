// The live Api (WEB-1a, WIRE-1..3, FR-UX-13): `startWorld` makes the real intake call; `getLedger` reads `GET {base}/costs`, `getWorlds` walks `GET {base}/worlds`
// pages, `getDecisions` walks `GET {base}/cards` pages and `decide` answers one card with one POST (the
// person's tap, never a retry). `getConnectors` reads `/v1/connectors`. Profile defaults and preferences are in-memory page choices; other methods are NotBuilt and
// fetches nothing. With no base url nothing is fetched at all. It never imports the fixtures, so sample
// numbers cannot pass as live (HR-1..HR-7). Failures are the shared `TiloApiError` (src/api/http.ts).
import type { IntakeResult } from "../../api/client";
import { HttpClient, type QuickIntakeResult, TiloApiError, reasonOf } from "../../api/http";
import { rememberIntake } from "../../api/intakes";
import { isSampleHidden, wantsSample } from "../sample/sampleChoice";
import { API_METHODS, type Api, type ApiMethod } from "./index";
import { connectorsFromList } from "./live/connectorsFromList";
import {
  type CardFeedItem,
  answerOption,
  decisionKey,
  decisionsFromCards,
  needsFields,
} from "./live/decisionsFromCards";
import { type CostReport, ledgerFromCosts } from "./live/ledgerFromCosts";
import { notificationsFromFeed } from "./live/notificationsFromFeed";
import { profileDefaults } from "./live/profileDefaults";
import {
  captureOfBody,
  isLearnBody,
  isSkillRow,
  saveBody,
  skillsOfBody,
  versionOfBody,
} from "./live/skillsFromApi";
import { worldFromIntake } from "./live/worldFromIntake";
import { STATE_OF, type WorldListItem, worldsFromList } from "./live/worldsFromList";
import { nameInitials } from "./nameInitials";
import type { Dec, DecisionKey, Effort, QuickReply, TierKey, Today, User } from "./types";

export class NotBuilt extends Error {
  readonly code = "not_built";
  constructor(method: ApiMethod) {
    super(`${method} is not connected yet`);
    this.name = "NotBuilt";
  }
}

export interface LiveApiOptions {
  /** The API origin; trailing slashes are trimmed. Without it, every method is NotBuilt. */
  baseUrl?: string;
  fetch?: typeof fetch;
  /** SEC-10: the App Check token getter; the Park pages' requests carry `X-Firebase-AppCheck` like the rest of the app. */
  appCheckToken?: (() => Promise<string | null>) | undefined;
  /** SEC-15: the Firebase ID token getter; every Park request carries `Authorization: Bearer` like the rest of the app. */
  authToken?: (() => Promise<string | null>) | undefined;
}

export interface Identity {
  name: string | null;
  email: string | null;
}

const titleCase = (w: string): string => w.charAt(0).toUpperCase() + w.slice(1);

/** The signed-in person as the Home greeting needs them: nothing but what the sign-in session holds. */
export function userOf(who: Identity): User | null {
  const email = who.email?.trim() ?? "";
  const name =
    who.name?.trim() ||
    email
      .split("@")[0]
      ?.replace(/[._-]+/g, " ")
      .trim() ||
    "";
  if (!name) return null;
  const words = name.split(/\s+/).map(titleCase);
  const first = words[0] ?? name;
  const initials = nameInitials(name);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
  return {
    first,
    name: who.name?.trim() || words.join(" "),
    initials,
    email,
    title: "",
    org: "",
    plan: "",
    tz,
    lang: "",
    hours: "",
  };
}

/** Today from the clock: a date is true wherever it comes from. */
export function todayOf(d: Date): Today {
  const part = (o: Intl.DateTimeFormatOptions): string =>
    new Intl.DateTimeFormat("en-GB", o).format(d);
  return {
    long: part({ weekday: "long", day: "numeric", month: "long" }).replace(",", ""),
    short: part({ weekday: "short", day: "numeric", month: "short" }).replace(",", ""),
    time: part({ hour: "2-digit", minute: "2-digit", hour12: false }),
  };
}

const BAD_REPLY = "Tilo sent a reply this page could not read.";

/** One Quick ask (`mode=quick`): the server's answer or offer read strictly into a Park `QuickReply`. */
async function quickAsk(
  http: HttpClient,
  query: string,
): Promise<{ data: QuickReply; source: "live" }> {
  let r: QuickIntakeResult;
  try {
    r = await http.submitIntake(query, [], "quick");
  } catch (e) {
    if (e instanceof TiloApiError) throw e;
    throw new TiloApiError(BAD_REPLY, 200, true, true);
  }
  return { data: r, source: "live" };
}

const isRows = (v: unknown): boolean =>
  Array.isArray(v) && v.every((r) => typeof r?.usd === "number");

/** A body that is not a cost report is an unreadable reply, never a Ledger. */
function isCostReport(v: unknown): v is CostReport {
  const r = v as Partial<Record<keyof CostReport, unknown>> | null;
  const totals = r?.totals as { usd?: unknown } | null | undefined;
  return (
    typeof totals === "object" &&
    totals !== null &&
    typeof totals.usd === "number" &&
    isRows(r?.by_profile) &&
    isRows(r?.by_task_type)
  );
}

/** At most 1,000 worlds, the newest (BQ-WIRE2-5): a server that never ends the walk cannot hang the page. */
const MAX_PAGES = 10;

const isItem = (v: unknown): v is WorldListItem => {
  const i = v as Partial<Record<keyof WorldListItem, unknown>> | null;
  return (
    typeof i === "object" &&
    i !== null &&
    typeof i.world_id === "string" &&
    typeof i.status === "string" &&
    Object.hasOwn(STATE_OF, i.status) &&
    (i.title === null || typeof i.title === "string") &&
    (i.created_at === null || typeof i.created_at === "string")
  );
};

/** A body that is not a world list page is an unreadable reply, never worlds (an unknown status too, HR-5). */
function isWorldPage(v: unknown): v is { worlds: WorldListItem[]; next_cursor: string | null } {
  const p = v as { worlds?: unknown; next_cursor?: unknown } | null;
  return (
    typeof p === "object" &&
    p !== null &&
    Array.isArray(p.worlds) &&
    p.worlds.every(isItem) &&
    (p.next_cursor === null || typeof p.next_cursor === "string")
  );
}

const KINDS = new Set(["needs_you", "meeting", "gate", "consent"]);
const isText = (v: unknown): v is string => typeof v === "string";
const isTexts = (v: unknown): boolean => Array.isArray(v) && v.every(isText);
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

/** A card the Api can show and answer: its kind, words and options are read, the option a tap sends exists, the
 * gate's exact action and recipients (or the consent scopes) the person sees are there, and it matches its wrapper. */
function isFeedItem(v: unknown): v is CardFeedItem {
  if (!isObject(v) || !isText(v.world_id) || !isText(v.card_id) || !isObject(v.card)) return false;
  const c = v.card as Record<string, unknown>;
  const gate = c.gate as { action?: { exact?: unknown }; recipients?: unknown } | null;
  const consent = c.consent as { scopes?: unknown } | null;
  return (
    c.world_id === v.world_id &&
    c.id === v.card_id &&
    isText(c.kind) &&
    KINDS.has(c.kind) &&
    isText(c.what_happened) &&
    isText(c.why_it_matters) &&
    Array.isArray(c.options) &&
    c.options.every((o) => isObject(o) && isText(o.id) && isText(o.label)) &&
    (c.kind !== "gate" || (isText(gate?.action?.exact) && isTexts(gate?.recipients))) &&
    (c.kind !== "consent" || isTexts(consent?.scopes)) &&
    answerOption(c as unknown as CardFeedItem["card"]) !== null
  );
}

/** A body that is not a card feed page is an unreadable reply, never decisions. */
function isCardPage(v: unknown): v is { cards: CardFeedItem[]; next_cursor: string | null } {
  const p = v as { cards?: unknown; next_cursor?: unknown } | null;
  return (
    isObject(p) &&
    Array.isArray(p.cards) &&
    p.cards.every(isFeedItem) &&
    (p.next_cursor === null || isText(p.next_cursor))
  );
}

/** How `decide` finds its card again: only keys this Api served (BQ-WIRE3-1). */
interface Answerable {
  path: string;
  option: string;
}

export function createLiveApi(options: LiveApiOptions = {}): Api {
  const stubs = API_METHODS.map((m) => [m, () => Promise.reject(new NotBuilt(m))]);
  const api = Object.fromEntries(stubs) as unknown as Api;
  const baseUrl = options.baseUrl?.trim();
  if (!baseUrl) return api;
  const prefs = new Map<string, unknown>();
  api.setPref = async (key, value) => {
    prefs.set(key, structuredClone(value));
    return { data: { ok: true }, source: "live" };
  };
  api.getProfileSettings = async () => {
    const data = profileDefaults();
    const quiet = prefs.get("quiet");
    if (typeof quiet === "boolean") data.quiet.on = quiet;
    return { data, source: "live" };
  };
  const http = new HttpClient({
    baseUrl,
    ...(options.fetch ? { fetch: options.fetch } : {}),
    ...(options.appCheckToken ? { appCheckToken: options.appCheckToken } : {}),
    ...(options.authToken ? { authToken: options.authToken } : {}),
  });
  api.getLedger = async () => {
    const report = await http.getJson("/costs");
    if (!isCostReport(report)) throw new TiloApiError(BAD_REPLY, 200, true);
    return { data: ledgerFromCosts(report), source: "live" };
  };
  api.getConnectors = async () => {
    const data = connectorsFromList(await http.getJson("/v1/connectors"));
    if (data === null) throw new TiloApiError(BAD_REPLY, 200, true);
    return { data, source: "live" };
  };
  api.getNotifications = async () => ({
    data: notificationsFromFeed(await http.getJson("/v1/notifications?limit=100")),
    source: "live",
  });
  api.getWorlds = async (_dec, added) => {
    const items: WorldListItem[] = [];
    let cursor: string | null = null;
    for (let n = 0; n < MAX_PAGES && (n === 0 || cursor !== null); n++) {
      const query = cursor === null ? "" : `&cursor=${encodeURIComponent(cursor)}`;
      const sample = wantsSample() ? "&include_sample=1" : ""; // STARTER-1: "Show sample project"
      const body = await http.getJson(`/worlds?limit=100${sample}${query}`);
      if (!isWorldPage(body)) throw new TiloApiError(BAD_REPLY, 200, true);
      items.push(...body.worlds);
      cursor = body.next_cursor;
    }
    // STARTER-1: a person's "Hide" is this browser's; the server stores nothing about it.
    const live = worldsFromList(isSampleHidden() ? items.filter((i) => i.sample !== true) : items);
    const liveIds = new Set(live.map((w) => w.id));
    return { data: [...added.filter((w) => !liveIds.has(w.id)), ...live], source: "live" };
  };
  // Taught skills (SKILLS-3, FR-SKL-04): the library is `GET /v1/skills`; Learn has nothing served but the list.
  api.getSkills = async () => {
    const skills = skillsOfBody(await http.getJson("/v1/skills"));
    if (!skills) throw new TiloApiError(BAD_REPLY, 200, true);
    return { data: skills, source: "live" };
  };
  api.getLearn = async () => {
    if (!isLearnBody(await http.getJson("/v1/learn"))) throw new TiloApiError(BAD_REPLY, 200, true);
    return { data: { rates: [], reviews: [], helpers: [], tools: [] }, source: "live" };
  };
  // One POST, no retry. A draft the server cannot take (a team scope, a timed trigger) is refused here, never sent as
  // something else; only a 201 with the saved record is an Ack.
  api.saveSkill = async (skill) => {
    const body = skill.draft ? saveBody(skill.name, skill.draft) : null;
    if (!body) {
      throw new TiloApiError(
        "Tilo can only save a skill for you that runs when you ask, for now.",
        422,
        false,
        true,
      );
    }
    if (!isSkillRow(await http.postJson("/v1/skills", body)))
      throw new TiloApiError(BAD_REPLY, 201, true, true);
    return { data: { ok: true }, source: "live" };
  };
  // Teach a skill by describing it (SKILLS-5): one POST each, no retry; only a readable answer is data.
  api.captureSkill = async (text) => {
    const data = captureOfBody(
      await http.postJson("/v1/skills/captures", { method: "describe", text }),
    );
    if (!data) throw new TiloApiError(BAD_REPLY, 201, true, true);
    return { data, source: "live" };
  };
  api.proposeVersion = async (captureId) => {
    const path = `/v1/skills/captures/${encodeURIComponent(captureId)}/version`;
    const data = versionOfBody(await http.postJson(path, {}));
    if (!data) throw new TiloApiError(BAD_REPLY, 200, true, true);
    return { data, source: "live" };
  };
  const served = new Map<string, Answerable>();
  const answered: Dec = {};
  api.getDecisions = async () => {
    const items: CardFeedItem[] = [];
    let cursor: string | null = null;
    for (let n = 0; n < MAX_PAGES && (n === 0 || cursor !== null); n++) {
      const query = cursor === null ? "" : `&cursor=${encodeURIComponent(cursor)}`;
      const body = await http.getJson(`/cards?limit=100${query}`);
      if (!isCardPage(body)) throw new TiloApiError(BAD_REPLY, 200, true);
      items.push(...body.cards);
      cursor = body.next_cursor;
    }
    served.clear(); // a card that left the feed can no longer be answered from a stale key (BQ-WIRE3-1)
    for (const { world_id, card_id, card } of items) {
      if (needsFields(card)) continue; // typed in the fields form: a tap on it would answer `provide` with nothing
      const path = `/worlds/${encodeURIComponent(world_id)}/cards/${encodeURIComponent(card_id)}/answer`;
      served.set(decisionKey(world_id, card_id), { path, option: answerOption(card) as string });
    }
    return { data: decisionsFromCards(items), source: "live" };
  };
  // One POST per call: no retry, no refresh (a person answers once, HR-1..HR-7). A 404 means the session's world is
  // not the card's world, so the page offers "Open in world" (code open_in_world; `Decision.world` is that world).
  api.decide = async (key: DecisionKey) => {
    const target = served.get(key);
    if (!target) throw new TiloApiError("That decision is not on this page any more.", null, false);
    let body: unknown;
    try {
      body = await http.postJson(target.path, { option: target.option });
    } catch (e) {
      if (e instanceof TiloApiError && e.status === 404) {
        throw new TiloApiError(e.message, 404, false, true, "open_in_world");
      }
      throw e;
    }
    const outcome = isObject(body) ? body.outcome : undefined;
    if (outcome === "rejected")
      throw new TiloApiError(reasonOf(200, JSON.stringify(body)), 200, false, true);
    if (outcome !== "answered") throw new TiloApiError(BAD_REPLY, 200, true, true);
    answered[key] = true;
    return { data: { ok: true, dec: { ...answered } }, source: "live" };
  };
  // The real intake call, the legacy S-01's (FR-UX-13): one POST of the text alone (the intake has no size, routine
  // or workspace field; the size only picks the tier shown, BQ-UX13-2). A reply the page cannot read, including
  // one without its `files`, is a TiloApiError, never a TypeError or a world. The brief goes to S-02.
  api.startWorld = (async (mode: TierKey, query: string, effort?: Effort) => {
    // Quick (COST-FAST-1): a direct answer or an offer to switch. No world, no event, and nothing is remembered.
    if (effort === "quick") return quickAsk(http, query);
    let intake: IntakeResult;
    try {
      intake = await http.submitIntake(query, []);
    } catch (e) {
      if (e instanceof TiloApiError) throw e;
      throw new TiloApiError(BAD_REPLY, 200, true, true);
    }
    if (!isText(intake?.task_id) || intake.task_id === "" || !isObject(intake.brief)) {
      throw new TiloApiError(BAD_REPLY, 200, true, true);
    }
    rememberIntake(intake);
    return { data: { ok: true, world: worldFromIntake(mode, intake, query) }, source: "live" };
  }) as Api["startWorld"];
  // The lifetime-cap pop-up's feedback (SEC-16): resolves only on the server's `{received: true}`.
  api.submitFeedback = async (words: string) => {
    await http.submitFeedback(words);
    return { data: { ok: true }, source: "live" };
  };
  return api;
}
