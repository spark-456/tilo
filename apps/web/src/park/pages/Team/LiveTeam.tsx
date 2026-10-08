// TEAM-WEB (FR-TEAM-02/04, FR-ACC-01): the Team page on a live Api. The state machine (`useLiveTeam`) reads
// GET /v1/team through api.getTeamLive and sends each Owner-only write through api.writeTeam: optimistic, rolled
// back on failure, refetched on a stale write (409), one write at a time. The body shows only what the server
// sends: members by id (no names exist yet), their limits, the five switches, the capability matrix and pending
// invites. Not built, so not offered: cancel or resend an invite, changing an invite's role, the coverage
// card, helped-Tilo and activity numbers, the per-skill saved level (FR-ACC-02). Fixture mode never gets here.
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { TiloApiError } from "../../../api/http";
import type { Api } from "../../api";
import {
  TEAM_ROLES,
  type TeamOp,
  type TeamView,
  applyOp,
  isStale,
  readErrorText,
  teamErrorText,
} from "../../api/live/teamLive";
import { Button } from "../../components";
import { Members } from "./Members";
import { MatrixCard, RulesCard } from "./Rules";
import { agentArt } from "./teamKit";
import { type Member, type MemberView, isValidEmail } from "./teamModel";

export type LiveState =
  | { phase: "probing" }
  | { phase: "fixture" }
  | { phase: "error"; text: string }
  | { phase: "ready"; view: TeamView };

export interface LiveTeam {
  state: LiveState;
  /** The line under the heading: the last failure, else why the controls are off. Always present, so nothing shifts. */
  note: string;
  busy: boolean;
  isOwner: boolean;
  send: (op: TeamOp) => Promise<boolean>;
}

export const READ_ONLY = "Only an Owner can change the team. You can look at it.";

export function useLiveTeam(api: Api): LiveTeam {
  const [state, setState] = useState<LiveState>({ phase: "probing" });
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    api.getTeamLive().then(
      (r) =>
        alive.current && setState(r.data ? { phase: "ready", view: r.data } : { phase: "fixture" }),
      // A TiloApiError means a live server answered; anything else (NotBuilt) is the sample path's to handle.
      (e: unknown) =>
        alive.current &&
        setState(
          e instanceof TiloApiError
            ? { phase: "error", text: readErrorText(e) }
            : { phase: "fixture" },
        ),
    );
    return () => {
      alive.current = false;
    };
  }, [api]);

  const view = state.phase === "ready" ? state.view : null;
  const send = useCallback(
    async (op: TeamOp): Promise<boolean> => {
      if (!view || locked.current) return false;
      locked.current = true;
      setBusy(true);
      setFailure("");
      const show = (v: TeamView) => alive.current && setState({ phase: "ready", view: v });
      show(applyOp(view, op));
      try {
        const r = await api.writeTeam(op);
        if (r.data) show(r.data);
        return true;
      } catch (e) {
        show(view); // roll back
        if (alive.current) setFailure(teamErrorText(e));
        if (isStale(e)) {
          const fresh = await api.getTeamLive().catch(() => null);
          if (fresh?.data) show(fresh.data);
        }
        return false;
      } finally {
        locked.current = false;
        if (alive.current) setBusy(false);
      }
    },
    [api, view],
  );
  const isOwner = view?.me.role === "Owner";
  return { state, note: failure || (view && !isOwner ? READ_ONLY : ""), busy, isOwner, send };
}

/** The always-present status line (a reserved height, so a message never moves the page). */
export function StatusLine({ text }: { text: string }) {
  return (
    <output className="park-team-intro" style={{ display: "block", minHeight: 20, margin: 0 }}>
      {text}
    </output>
  );
}

const SWITCH_COPY: Record<string, [string, string]> = {
  spend: ["Spending money", "Always asks. This can’t be switched off."],
  share: ["Sharing anything outside the company", "Always asks. This can’t be switched off."],
  undo: ["Actions that can’t be undone", "Always asks. This can’t be switched off."],
  // BQ-TEAMRT-3: the engine does not read this switch yet; the page says so instead of implying it does.
  tools: ["Giving a skill more access to a tool", "Saved; not enforced yet"],
  weekend: ["Routines that fall on a weekend", "Hold until Monday morning"],
};

/** INR minor units (paise) in words; null is a limit nobody set, or one this person may not see. */
export const limitText = (minor: number | null): string =>
  minor === null ? "—" : `₹${(minor / 100).toLocaleString("en-IN")}`;

function memberViews(view: TeamView): MemberView[] {
  const people = view.members.map((m) => {
    const p: Member = {
      id: m.id,
      name: m.id,
      email: "",
      dept: "",
      role: m.role,
      active: "",
      c: "#E2ECFB",
      ...(m.id === view.me.id ? { you: true } : {}),
    };
    return {
      p,
      sub: p.you ? "This is you" : "On this team",
      limit: limitText(m.limit_minor),
      active: "—",
      helped: "—",
      bar: "0%",
      isBackup: false,
      facts: [
        ["ROLE", m.role],
        ["SPEND LIMIT", m.limit_minor === null ? "None set" : limitText(m.limit_minor)],
      ],
    } satisfies MemberView;
  });
  const invited = view.invites.map((i) => {
    const p: Member = {
      id: i.id,
      name: i.email,
      email: i.email,
      dept: "",
      role: i.role,
      active: "Pending",
      c: "transparent",
      pending: true,
    };
    return {
      p,
      sub: "Invited",
      limit: "—",
      active: "Pending",
      helped: "—",
      bar: "0%",
      isBackup: false,
      facts: [["INVITED AS", i.role]],
    } satisfies MemberView;
  });
  return [...people, ...invited];
}

function LimitEditor({ id, minor, disabled, onSave }: LimitProps) {
  const [value, setValue] = useState(minor === null ? "" : String(minor / 100));
  const rupees = Number(value);
  const ok = value.trim() === "" || (Number.isFinite(rupees) && rupees >= 0 && rupees <= 1e9);
  const save = () => onSave(id, value.trim() === "" ? null : Math.round(rupees * 100));
  return (
    <span className="park-team-field">
      <input
        className="park-team-input"
        aria-label={`Spend limit for ${id} in rupees`}
        placeholder="No limit"
        inputMode="decimal"
        value={value}
        disabled={disabled}
        onChange={(e) => setValue(e.target.value)}
      />
      <button type="button" className="park-team-btn" disabled={disabled || !ok} onClick={save}>
        Save limit
      </button>
    </span>
  );
}
interface LimitProps {
  id: string;
  minor: number | null;
  disabled: boolean;
  onSave: (id: string, minor: number | null) => void;
}

/** The members, rules and matrix cards for a ready live team. */
export function LiveBody({
  live,
  view,
  toast,
}: { live: LiveTeam; view: TeamView; toast: (m: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const { send, busy, isOwner } = live;
  const off = !isOwner || busy;
  const done = (ok: Promise<boolean>, said: string) => void ok.then((y) => y && toast(said));
  const rules = view.switches.map((s) => {
    const [label, note] = SWITCH_COPY[s.key] ?? [s.key, ""];
    return [s.key, label, note, s.on] as [string, string, string, boolean];
  });
  const matrix = view.capabilities.map((c): [string, number] => [
    c.label,
    TEAM_ROLES.reduce((bits, r, i) => (c.roles.includes(r) ? bits | (1 << i) : bits), 0),
  ]);
  const limits = new Map(view.members.map((m) => [m.id, m.limit_minor]));
  return (
    <>
      <Members
        views={memberViews(view)}
        roles={TEAM_ROLES}
        open={open}
        onOpen={(id) => setOpen((o) => (o === id ? null : id))}
        onRole={(p, role) =>
          done(send({ kind: "role", id: p.id, role }), `${p.name} is now ${role}`)
        }
        canChange={(p) => !off && !p.pending && !p.you}
        canRemove={(p) => isOwner && !p.pending}
        onRemove={(p) => {
          setOpen(null);
          done(
            send({ kind: "remove", id: p.id }),
            `${p.name} was removed. Their worlds move to you`,
          );
        }}
        extra={(p): ReactNode =>
          p.pending || !isOwner ? null : (
            <LimitEditor
              key={`${p.id}:${limits.get(p.id) ?? ""}`}
              id={p.id}
              minor={limits.get(p.id) ?? null}
              disabled={busy}
              onSave={(id, limitMinor) =>
                done(send({ kind: "limit", id, limitMinor }), "Spend limit saved")
              }
            />
          )
        }
      />
      <div className="park-team-two">
        <RulesCard
          rules={rules}
          on={Object.fromEntries(view.switches.map((s) => [s.key, s.on]))}
          art={agentArt(false)}
          locked={view.switches.filter((s) => s.must_ask).map((s) => s.key)}
          readOnly={off}
          log={[]}
          onToggle={(key, next) => done(send({ kind: "switch", key, on: next }), "Saved")}
        />
        <MatrixCard team={{ roles: [...TEAM_ROLES], matrix }} />
      </div>
    </>
  );
}

/** The invite field for the heading: Owner only, a valid address, one write at a time. */
export function LiveInvite({ live, toast }: { live: LiveTeam; toast: (m: string) => void }) {
  const [email, setEmail] = useState("");
  const off = !live.isOwner || live.busy;
  const valid = isValidEmail(email);
  const invite = () => {
    const to = email.trim();
    if (off || !valid) return;
    void live.send({ kind: "invite", email: to, role: "Member" }).then((ok) => {
      if (!ok) return;
      setEmail("");
      toast(`Invite saved for ${to}. No email goes out yet`);
    });
  };
  return (
    <div className="park-team-invite">
      <div className="park-team-field">
        <input
          className="park-team-input"
          aria-label="Invite by email"
          placeholder="name@company.com"
          value={email}
          disabled={!live.isOwner}
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && invite()}
        />
      </div>
      <Button variant="primary" disabled={off || !valid} onClick={invite}>
        Invite
      </Button>
    </div>
  );
}
