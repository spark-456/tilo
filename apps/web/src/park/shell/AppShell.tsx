// THROWAWAY (WEB-3b validation only).
import { type ReactNode, useEffect, useState, useSyncExternalStore } from "react";
import type { Notification, User } from "../api/types";
import { useApp, useParkApi, useParkStore } from "../app/context";
import { Toast } from "../components";
import "./park.shell.css";
import { AccountMenu } from "./AccountMenu";
import { BootSplash } from "./BootSplash";
import { CityBackdrop } from "./CityBackdrop";
import { NotificationsPopover } from "./NotificationsPopover";
import { TopNav } from "./TopNav";
import { WorldLoader } from "./WorldLoader";

export function AppShell({ children }: { children: ReactNode }) {
  const app = useApp();
  const api = useParkApi();
  const store = useParkStore();
  const s = useSyncExternalStore(store.subscribe, store.getState);
  const [notes, setNotes] = useState<Notification[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let live = true;
    api.getNotifications().then((r) => live && setNotes(r.data)).catch(() => undefined);
    api.getUser().then((r) => live && setUser(r.data)).catch(() => undefined);
    setReady(true);
    return () => {
      live = false;
    };
  }, [api]);
  return (
    <>
      <BootSplash ready={ready} />
      <CityBackdrop />
      <TopNav />
      <NotificationsPopover items={notes} />
      {user ? <AccountMenu user={user} /> : null}
      <main className="park-shell__main">
        {app.page === "home" ? children : <div className="park-shell__column">{children}</div>}
      </main>
      {s.toast ? (
        <Toast
          message={s.toast.message}
          {...(s.toast.actionLabel !== undefined ? { actionLabel: s.toast.actionLabel } : {})}
          {...(s.toast.action ? { onAction: s.toast.action } : {})}
          onDismiss={store.dismissToast}
        />
      ) : null}
      <WorldLoader />
    </>
  );
}
