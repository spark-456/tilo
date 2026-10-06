// WEB-10 Team page: the pure view-model, ported from the `renderVals` of design "Tilo App Team.dc.html"
// (user's prototype, ADR-0003a). No React, no clock: the coverage rows, the member rows and their facts
// are computed from the Api data plus the page's local state (people, backups).
import type { Learn, Skill, Team, World } from "../../api/types";

export type Member = Omit<Team["people"][number], "limit"> & {
  limit?: string | undefined;
  pending?: boolean;
};
/** Coverage row id -> person id of the backup approver added for it. */
export type Backups = Record<string, string>;
export interface Loaded {
  team: Team;
  helpers: Learn["helpers"];
  skills: Skill[];
  worlds: World[];
}

/** The spend limit a role gets (an approver keeps the limit the fixture gave them until the role changes). */
const LIMIT: Record<string, string> = {
  Owner: "No limit",
  Approver: "£1,000",
  Member: "£250",
  Viewer: "—",
};

export const initialsOf = (name: string): string =>
  name
    .split(" ")
    .map((s) => s[0])
    .join("");

export interface CoverRow {
  id: string;
  what: string;
  ids: string[];
  who: Member[];
  names: string;
  wait: string;
  slow: boolean;
  single: boolean;
  opts: { id: string; name: string }[];
}

export function coverRows(team: Team, people: readonly Member[], backups: Backups): CoverRow[] {
  return team.coverage.map((c) => {
    const extra = backups[c.id];
    const ids = extra ? [...c.who, extra] : c.who;
    const who = ids.flatMap((id) => people.find((p) => p.id === id) ?? []);
    const single = who.length < 2;
    return {
      id: c.id,
      what: c.what,
      ids,
      who,
      single,
      names: who.map((p) => p.name.split(" ")[0]).join(", ") + (single ? " only" : ""),
      wait: extra && c.slow ? "About 20 min" : c.wait,
      slow: !!c.slow && !extra,
      opts: people
        .filter((p) => !p.pending && !p.you && p.role !== "Viewer" && !ids.includes(p.id))
        .map((p) => ({ id: p.id, name: p.name })),
    };
  });
}

export interface MemberView {
  p: Member;
  sub: string;
  limit: string;
  active: string;
  helped: string;
  bar: string;
  isBackup: boolean;
  facts: [string, string][];
}

export function memberViews(
  people: readonly Member[],
  rows: readonly CoverRow[],
  backups: Backups,
  data: Loaded,
): MemberView[] {
  const most = Math.max(1, ...data.helpers.map((x) => x.n));
  const lent = Object.values(backups);
  return people.map((p) => {
    const hp = data.helpers.find((x) => x.id === p.id);
    const list = (xs: string[]) => (xs.length ? xs.join(", ") : "None");
    const signs = rows.filter((r) => r.ids.includes(p.id)).map((r) => r.what);
    const owns = data.skills.filter((s) => s.owner === p.name).map((s) => s.name);
    const worlds = data.worlds.filter((w) => w.owner === p.name).map((w) => w.short);
    const base = {
      p,
      isBackup: lent.includes(p.id),
      helped: hp ? String(hp.n) : "0",
      bar: hp ? `${Math.round((hp.n / most) * 100)}%` : "0%",
    };
    if (p.pending) {
      return {
        ...base,
        sub: "Invite sent · just now",
        limit: "—",
        active: "Pending",
        facts: [
          ["INVITED AS", p.role],
          ["SENT", "Just now · expires in 7 days"],
        ],
      };
    }
    return {
      ...base,
      sub: `${p.email} · ${p.dept}`,
      limit: p.limit && p.role === "Approver" ? p.limit : (LIMIT[p.role] ?? "—"),
      active: p.active,
      facts: [
        [
          "SIGNS OFF",
          p.role === "Owner"
            ? "Everything, as owner"
            : signs.length
              ? signs.join(", ")
              : "Nothing yet",
        ],
        ["OWNS SKILLS", list(owns)],
        ["OWNS WORLDS", list(worlds)],
        ["HELPED TILO", hp ? hp.impact : "No answers or fixes yet"],
      ],
    };
  });
}
