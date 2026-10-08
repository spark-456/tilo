// The notifications popover (README "Shell > Notifications popover"; reference `Tilo App.dc.html`): 392 wide,
// a header with Settings, then one row per notification: a 36px tile, title and sub, and the time. An item
// whose decision is approved reads "You approved..." (or "You sent...") with a green tile. A row opens its
// world (through the loader) or Connectors; Settings opens Profile on the notifications tab.
import type { ReactNode } from "react";
import type { Dec, Decision, Notification } from "../api/types";
import { Popover } from "../components";
import { icon } from "./kit";

type Kind = Notification["kind"];

const TILE_ICON: Record<Kind, string> = { needs: "flag", done: "check", warn: "plug" };
/** The title once its decision is approved: the decision's designed copy, else "You approved" (FR-UX-11). */
const approvedTitle = (d: Decision | undefined): string => d?.approvedTitle || "You approved";

/** Where the list came from: read, a service with no notifications route yet, or a read that failed. */
export type FeedStatus = "ready" | "not-built" | "error";
const EMPTY_LINE: Record<Exclude<FeedStatus, "ready">, string> = {
  "not-built": "Not connected yet",
  error: "Notifications could not load",
};

export interface NotificationsPopoverProps {
  notifications: readonly Notification[];
  status?: FeedStatus;
  decisions: readonly Decision[];
  dec: Dec;
  onOpen: (n: Notification) => void;
  onSettings: () => void;
  onClose: () => void;
}

export function NotificationsPopover({
  notifications,
  status = "ready",
  decisions,
  dec,
  onOpen,
  onSettings,
  onClose,
}: NotificationsPopoverProps): ReactNode {
  return (
    <Popover label="Notifications" width={392} className="park-shell__notif" onClose={onClose}>
      <div className="park-shell__pophead">
        <span className="park-shell__poptitle">Notifications</span>
        <button type="button" className="park-shell__settings" onClick={onSettings}>
          Settings
        </button>
      </div>
      {status !== "ready" ? (
        <output className="park-shell__nempty">{EMPTY_LINE[status]}</output>
      ) : null}
      {notifications.map((n) => {
        const approved = n.dec !== undefined && dec[n.dec] === true;
        const kind: Kind = approved ? "done" : n.kind;
        return (
          <button
            key={n.id}
            type="button"
            data-kind={kind}
            className="park-shell__nrow"
            onClick={() => onOpen(n)}
          >
            <span className={`park-shell__ntile park-shell__ntile--${kind}`}>
              {icon(TILE_ICON[kind], 16)}
            </span>
            <span className="park-shell__ntext">
              <span className="park-shell__ntitle">
                {approved ? approvedTitle(decisions.find((d) => d.k === n.dec)) : n.title}
              </span>
              <span className="park-shell__nsub">{n.sub}</span>
            </span>
            <span className="park-shell__ntime">{n.t}</span>
          </button>
        );
      })}
    </Popover>
  );
}
