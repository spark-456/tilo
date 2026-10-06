// THROWAWAY (WEB-3b validation only).
import { type ReactNode, useSyncExternalStore } from "react";
import type { Notification } from "../api/types";
import { useApp, useParkStore } from "../app/context";
import { Popover } from "../components";
import { getKit } from "./kit";

const KIND = {
  needs: ["needs", "flag"],
  done: ["done", "check"],
  warn: ["warn", "plug"],
} as const;

export function NotificationsPopover({ items }: { items: readonly Notification[] }) {
  const app = useApp();
  const store = useParkStore();
  const s = useSyncExternalStore(store.subscribe, store.getState);
  if (s.menu !== "notif") return null;
  const K = getKit();
  return (
    <Popover label="Notifications" width={392} onClose={store.closeMenu}>
      <div className="park-notif__head">
        <span className="park-notif__head-title">Notifications</span>
        <button
          type="button"
          className="park-notif__settings"
          onClick={() => store.go("profile", { tab: "notifications" })}
        >
          Settings
        </button>
      </div>
      {items.map((n) => {
        const approved = n.dec ? app.dec[n.dec] === true : false;
        const [tone, icon] = KIND[approved ? "done" : n.kind];
        const title = approved
          ? n.dec === "depot"
            ? "You approved Laptop Depot"
            : "You sent the supplier brief"
          : n.title;
        return (
          <button
            key={n.id}
            type="button"
            className="park-notif__row"
            onClick={() => (n.go[0] === "world" ? store.openWorld(n.go[1]) : store.go("connectors"))}
          >
            <span className={`park-notif__tile park-notif__tile--${tone}`}>{K.icon(icon, 16) as ReactNode}</span>
            <span className="park-notif__text">
              <span className="park-notif__title">{title}</span>
              <span className="park-notif__sub">{n.sub}</span>
            </span>
            <span className="park-notif__time">{n.t}</span>
          </button>
        );
      })}
    </Popover>
  );
}
