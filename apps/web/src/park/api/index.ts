// The Park api (WEB-1a; plan section 6.1): every method returns a Promise of `{ data, source }`, so a
// page can always say whether it shows sample data. One list of method names, one interface.
import type { UserSettings, UserSettingsUpdate } from "@tilo/contracts";
import type { TeamOp, TeamView } from "./live/teamLive";
import type {
  Ack,
  AgendaData,
  AgendaSlot,
  ApiResult,
  BuildHandoff,
  Connector,
  ConnectorTerms,
  Dec,
  DecideAck,
  Decision,
  DecisionKey,
  Learn,
  Ledger,
  Notification,
  Plan,
  ProfileSettings,
  QuickReply,
  Skill,
  SkillCapture,
  SkillVersion,
  StartAck,
  Team,
  TeamPolicy,
  TierKey,
  Today,
  User,
  World,
} from "./types";
export { HELPER_SUMMARY_FIXTURE } from "./fixtures/additive";

type R<T> = Promise<ApiResult<T>>;

export const API_METHODS = [
  "getUser",
  "getToday",
  "getDecisions",
  "getWorlds",
  "getPlans",
  "getSkills",
  "getLearn",
  "getLedger",
  "getAgenda",
  "getTeam",
  "getTeamLive",
  "getConnectors",
  "getNotifications",
  "getTeamPolicy",
  "getConnectorTerms",
  "getProfileSettings",
  "getUserSettings",
  "getBuildHandoff",
  "decide",
  "undo",
  "startWorld",
  "saveSkill",
  "captureSkill",
  "proposeVersion",
  "setToolLevel",
  "bookSlot",
  "addBackup",
  "setPref",
  "writeTeam",
  "saveUserSettings",
  "submitFeedback",
] as const;
export type ApiMethod = (typeof API_METHODS)[number];

export interface Api {
  getUser(): R<User>;
  getToday(): R<Today>;
  getDecisions(): R<Decision[]>;
  getWorlds(dec: Dec, added: readonly World[]): R<World[]>;
  getPlans(dec: Dec): R<Record<string, Plan>>;
  getSkills(): R<Skill[]>;
  getLearn(): R<Learn>;
  getLedger(): R<Ledger>;
  getAgenda(): R<AgendaData>;
  getTeam(): R<Team>;
  /** TEAM-WEB: `GET /v1/team`. Live: the server's view. Fixture: `data: null` (the page keeps its sample copy). Unbuilt: NotBuilt. */
  getTeamLive(): R<TeamView | null>;
  getConnectors(): R<Connector[]>;
  getNotifications(): R<Notification[]>;
  getTeamPolicy(): R<TeamPolicy>;
  getConnectorTerms(): R<ConnectorTerms>;
  getProfileSettings(): R<ProfileSettings>;
  getBuildHandoff(): R<BuildHandoff[]>;
  /** FR-SET-01/02: the signed-in person's saved profile and notification preferences (`GET /v1/me/settings`). */
  getUserSettings(): R<UserSettings>;
  /** The whole document, answered by the stored one. Saved only when the answer's `source` is "live". */
  saveUserSettings(update: UserSettingsUpdate): R<UserSettings>;
  decide(key: DecisionKey, text?: string, option?: string): R<DecideAck>;
  undo(key: DecisionKey): R<DecideAck>;
  startWorld(mode: TierKey, query: string): R<StartAck>;
  saveSkill(skill: Skill): R<Ack>;
  captureSkill(text: string): R<SkillCapture>;
  proposeVersion(captureId: string): R<SkillVersion>;
  setToolLevel(tool: string, level: number): R<Ack>;
  bookSlot(slot: AgendaSlot): R<Ack>;
  addBackup(personId: string): R<Ack>;
  setPref(key: string, value: unknown): R<Ack>;
  /** TEAM-WEB: one Owner-only team write; resolves with the view the server answers. Fixture: `data: null`, nothing written. */
  writeTeam(op: TeamOp): R<TeamView | null>;
  /** SEC-16: the lifetime-cap pop-up's feedback; confirmed only by a `source: "live"` answer. */
  submitFeedback(words: string): R<Ack>;
}

/**
 * Quick (COST-FAST-1): `startWorld` takes a third argument at run time, "quick", and then answers with a
 * `QuickReply` (a direct answer or an offer to switch) and makes no world. It is not in the `Api` type because
 * `types.test.ts` pins `startWorld`'s parameters and `keyof Api`; Thinking calls stay exactly two arguments.
 * `mode` is only the size on screen and never reaches the server. This one helper is the only caller.
 */
export interface QuickClientContext {
  route: string;
  history: { question: string; answer: string }[];
}
export const askQuick = (
  api: Api,
  mode: TierKey,
  query: string,
  context?: QuickClientContext,
): R<QuickReply> =>
  (
    api.startWorld as unknown as (
      m: TierKey,
      q: string,
      effort: "quick",
      files: File[],
      context?: QuickClientContext,
    ) => R<QuickReply>
  )(mode, query, "quick", [], context);

/**
 * WEB-W1: a Thinking start with attached files. Like `askQuick`, the files travel as a fourth run-time argument so
 * `startWorld`'s pinned two-parameter type is unchanged; the live Api sends them on the one `POST /intake`.
 */
export const startWithFiles = (
  api: Api,
  mode: TierKey,
  query: string,
  files: readonly File[],
): R<StartAck> =>
  (
    api.startWorld as unknown as (
      m: TierKey,
      q: string,
      effort: undefined,
      files: readonly File[],
    ) => R<StartAck>
  )(mode, query, undefined, files);
