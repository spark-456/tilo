// The Park api (WEB-1a; plan section 6.1): every method returns a Promise of `{ data, source }`, so a
// page can always say whether it shows sample data. One list of method names, one interface.
import type {
  Ack,
  Agenda,
  AgendaSlot,
  ApiResult,
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
  Skill,
  StartAck,
  Team,
  TeamPolicy,
  TierKey,
  Today,
  User,
  World,
} from "./types";

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
  "getConnectors",
  "getNotifications",
  "getTeamPolicy",
  "getConnectorTerms",
  "getProfileSettings",
  "decide",
  "undo",
  "startWorld",
  "saveSkill",
  "setToolLevel",
  "bookSlot",
  "addBackup",
  "setPref",
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
  getAgenda(): R<Agenda>;
  getTeam(): R<Team>;
  getConnectors(): R<Connector[]>;
  getNotifications(): R<Notification[]>;
  getTeamPolicy(): R<TeamPolicy>;
  getConnectorTerms(): R<ConnectorTerms>;
  getProfileSettings(): R<ProfileSettings>;
  decide(key: DecisionKey): R<DecideAck>;
  undo(key: DecisionKey): R<DecideAck>;
  startWorld(mode: TierKey, query: string): R<StartAck>;
  saveSkill(skill: Skill): R<Ack>;
  setToolLevel(tool: string, level: number): R<Ack>;
  bookSlot(slot: AgendaSlot): R<Ack>;
  addBackup(personId: string): R<Ack>;
  setPref(key: string, value: unknown): R<Ack>;
  /** SEC-16: the lifetime-cap pop-up's feedback; confirmed only by a `source: "live"` answer. */
  submitFeedback(words: string): R<Ack>;
}
