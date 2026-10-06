// The notifications popover (README "Shell > Notifications popover"; reference `Tilo App.dc.html`): 392 wide,
// a header with Settings, then one row per notification: a 36px tile, title and sub, and the time. An item
// whose decision is approved reads "You approved..." (or "You sent...") with a green tile. A row opens its
// world (through the loader) or Connectors; Settings opens Profile on the notifications tab.
import type { ReactNode } from "react";
import type { Dec, Notification } from "../api/types";
import { Popover } from "../components";
import { icon } from "./kit";

type Kind = Notification["kind"];

const TILE_ICON: Record<Kind, string> = { needs: "flag", done: "check", warn: "plug" };
const APPROVED: Record<NonNullable<Notification["dec"]>, string> = {
  depot: "You approved Laptop Depot",
  mail: "You sent the supplier brief",
};

export interface NotificationsPopoverProps {
  notifications: readonly Notification[];
  dec: Dec;
  onOpen: (n: Notification) => void;
  onSettings: () => void;
  onClose: () => void;
}

export function NotificationsPopover({
  notifications,
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
                {approved && n.dec ? APPROVED[n.dec] : n.title}
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
