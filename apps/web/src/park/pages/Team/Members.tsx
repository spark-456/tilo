// WEB-10 Team page: the members card (header row, one row per person, the open details block).
// Plan 8c: the Card padding 14/18/6 and the 36px "more" button are page-local variants.
// A real <table>; Team.css makes each <tr> a grid (the design's column template) and the table parts blocks.
import type { ReactNode } from "react";
import { icon } from "./teamKit";
import { type Member, type MemberView, initialsOf } from "./teamModel";

const HEADS = ["PERSON", "ROLE", "SPEND LIMIT", "HELPED TILO", "ACTIVE"];

interface MembersProps {
  views: readonly MemberView[];
  roles: readonly string[];
  open: string | null;
  onOpen: (id: string) => void;
  onRole: (p: Member, role: string) => void;
  canChange: (p: Member) => boolean;
  onRemove: (p: Member) => void;
  /** Without it no "Resend invite" is offered (live mode: no route resends). */
  onResend?: ((p: Member) => void) | undefined;
  /** Whether the remove / cancel button is offered for this person (default: yes, except for you). */
  canRemove?: ((p: Member) => boolean) | undefined;
  /** More controls at the end of the open details block (live mode: the spend limit). */
  extra?: ((p: Member) => ReactNode) | undefined;
}

export function Members({
  views,
  roles,
  open,
  onOpen,
  onRole,
  canChange,
  onRemove,
  onResend,
  canRemove,
  extra,
}: MembersProps) {
  return (
    <section className="park-team-card park-team-members" aria-label="Members">
      <div className="park-team-scroll">
        <table className="park-team-blk park-team-table">
          <thead className="park-team-blk">
            <tr className="park-team-grid park-team-head">
              {HEADS.map((t) => (
                <th key={t} scope="col">
                  {t}
                </th>
              ))}
              <td />
            </tr>
          </thead>
          {views.map((v) => (
            <Person
              key={v.p.id}
              v={v}
              roles={roles}
              isOpen={open === v.p.id}
              {...{ onOpen, onRole, canChange, onRemove, onResend, canRemove, extra }}
            />
          ))}
        </table>
      </div>
    </section>
  );
}

type PersonProps = Pick<
  MembersProps,
  "roles" | "onOpen" | "onRole" | "canChange" | "onRemove" | "onResend" | "canRemove" | "extra"
> & {
  v: MemberView;
  isOpen: boolean;
};

function Person({
  v,
  roles,
  isOpen,
  onOpen,
  onRole,
  canChange,
  onRemove,
  onResend,
  canRemove,
  extra,
}: PersonProps) {
  const { p } = v;
  return (
    <tbody className="park-team-blk park-team-person">
      <tr className="park-team-grid park-team-row">
        <td className="park-team-who">
          <span
            className={
              p.pending ? "park-team-avatar park-team-avatar--pending" : "park-team-avatar"
            }
            style={p.pending ? undefined : { background: p.c }}
          >
            {p.pending ? "?" : initialsOf(p.name)}
          </span>
          <div className="park-team-id">
            <div className="park-team-name">
              <span>{p.name}</span>
              {p.you ? <span className="park-team-tag park-team-tag--you">You</span> : null}
              {v.isBackup ? (
                <span className="park-team-tag park-team-tag--ok">Backup approver</span>
              ) : null}
            </div>
            <div className="park-team-sub">{v.sub}</div>
          </div>
        </td>
        <td>
          <select
            className="park-team-select"
            aria-label={`Role for ${p.name}`}
            value={p.role}
            disabled={!canChange(p)}
            onChange={(e) => onRole(p, e.target.value)}
          >
            {roles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </td>
        <td className="park-team-strong">{v.limit}</td>
        <td className="park-team-helped">
          <span className="park-team-strong">{v.helped}</span>
          <span className="park-team-track">
            <span className="park-team-fill" style={{ width: v.bar }} />
          </span>
        </td>
        <td
          className={
            v.active === "Now" ? "park-team-active park-team-active--now" : "park-team-active"
          }
        >
          {v.active}
        </td>
        <td>
          <button
            type="button"
            className="park-team-more"
            aria-label={`${isOpen ? "Hide" : "Show"} details for ${p.name}`}
            aria-expanded={isOpen}
            onClick={() => onOpen(p.id)}
          >
            {icon(isOpen ? "chevD" : "more", 15)}
          </button>
        </td>
      </tr>
      {isOpen ? (
        <tr className="park-team-blk">
          <td className="park-team-details" colSpan={6}>
            {v.facts.map(([k, val]) => (
              <div key={k} className="park-team-fact">
                <span className="park-team-fact-k">{k}</span>
                <span className="park-team-fact-v">{val}</span>
              </div>
            ))}
            <div className="park-team-actions">
              {p.pending && onResend ? (
                <button type="button" className="park-team-btn" onClick={() => onResend(p)}>
                  Resend invite
                </button>
              ) : null}
              {p.you || canRemove?.(p) === false ? null : (
                <button
                  type="button"
                  className="park-team-btn park-team-btn--red"
                  onClick={() => onRemove(p)}
                >
                  {p.pending ? "Cancel invite" : "Remove from team"}
                </button>
              )}
              {extra?.(p)}
            </div>
          </td>
        </tr>
      ) : null}
    </tbody>
  );
}
