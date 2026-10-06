// The Park app shell (README Architecture): the city backdrop, the top nav, the notifications popover and
// the account menu, the page outlet (the one <main>), the toast, the world loader and the boot splash.
// It renders no `[data-park]` root (ParkApp owns that one) and reads everything from ParkProvider: the app,
// the store and the Api. The notifications and the user come through the Api on mount, so a fixture Api
// raises the "Sample data" chip without any page asking for data. The city is STATIC (BQ-WEB-3).
import { type ReactNode, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { Decision, Notification, User } from "../api/types";
import { useApp, useExpectsSample, useParkApi, useParkStore } from "../app/context";
import { useParkRoute } from "../app/router";
import { Toast } from "../components";
import "../tokens/fonts";
import { AccountMenu } from "./AccountMenu";
import { BootSplash } from "./BootSplash";
import { CityBackdrop } from "./CityBackdrop";
import { NotificationsPopover } from "./NotificationsPopover";
import { TopNav } from "./TopNav";
import { WorldLoader } from "./WorldLoader";
import { loadShellFonts } from "./fonts";
import "./park.shell.css";
import { backdropScene } from "./scene";

const SIGN_OUT = "This is a prototype, so you stay signed in";

/** The bar along the nav's bottom edge while a world opens: 18% then 26 more per step, full at step 3. */
const loaderBar = (step: number): number => (step >= 3 ? 100 : 18 + step * 26);

export function AppShell({ children }: { children: ReactNode }) {
  const app = useApp();
  const store = useParkStore();
  const api = useParkApi();
  const route = useParkRoute();
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [connectorsOn, setConnectorsOn] = useState<number | null>(null);
  const [ready, setReady] = useState(false);
  const expectsSample = useExpectsSample();

  useEffect(() => {
    let live = true;
    const quiet = (): void => undefined; // a read that fails leaves the part empty; the page says why
    api
      .getNotifications()
      .then((r) => live && setNotifications(r.data))
      .catch(quiet);
    api
      .getDecisions()
      .then((r) => {
        if (!live) return;
        setDecisions(r.data);
        store.setDecisions(r.data);
      })
      .catch(quiet);
    api
      .getUser()
      .then((r) => live && setUser(r.data))
      .catch(quiet);
    api
      .getConnectors()
      .then((r) => live && setConnectorsOn(r.data.filter((c) => c.st !== "available").length))
      .catch(quiet);
    return () => {
      live = false;
    };
  }, [api, store]);

  // The first city is drawn after the boot splash has been committed and the design fonts have loaded
  // (the shell stays hidden under the splash until then, so no text swaps face and moves the nav).
  useEffect(() => {
    let live = true;
    backdropScene(app.time, app.motion);
    loadShellFonts().then(() => {
      if (live) setReady(true);
    });
    return () => {
      live = false;
    };
  }, [app.time, app.motion]);
  const scene = useMemo(
    () => (ready ? backdropScene(app.time, app.motion) : null),
    [ready, app.time, app.motion],
  );

  const page = route?.page ?? null;
  const inner = page !== "home";
  // Pages go to a world through the loader (README: always), everything else straight there.
  const open = (n: Notification): void => {
    if (n.go[0] === "world") store.openWorld(n.go[1]);
    else store.go("connectors");
  };
  const toast = state.toast;
  return (
    <>
      <CityBackdrop scene={scene} vw={app.vw} vh={app.vh} veiled={inner} />
      <TopNav
        page={page}
        needsLeft={app.needsLeft}
        night={app.night}
        menu={state.menu}
        unread={!state.read && app.needsLeft > 0}
        initials={user?.initials ?? ""}
        sample={state.sources.fixture}
        org={user?.org ?? null}
        reserveSample={expectsSample}
        booting={!ready}
        progress={state.wl ? loaderBar(state.wl.step) : null}
        go={(to) => store.go(to)}
        onToggleTime={() => store.setPref("time", app.night ? "day" : "night")}
        onBell={() => store.toggleMenu("notif")}
        onAvatar={() => store.toggleMenu("acct")}
      />
      {state.menu === "notif" ? (
        <NotificationsPopover
          notifications={notifications}
          decisions={decisions}
          dec={state.dec}
          onOpen={open}
          onSettings={() => store.go("profile", { tab: "notifications" })}
          onClose={store.closeMenu}
        />
      ) : null}
      {state.menu === "acct" ? (
        <AccountMenu
          user={user}
          connectorsOn={connectorsOn}
          go={(to) => store.go(to)}
          onSignOut={() => store.toast(SIGN_OUT)}
          onClose={store.closeMenu}
        />
      ) : null}
      {/* The same elements on every page, so a page swap never remounts the outlet (focus stays). */}
      <main className={`park-shell__main ${ready ? "" : "park-shell__booting"}`}>
        <div className={inner ? "park-shell__page" : undefined}>
          <div className={inner ? "park-shell__column" : undefined}>{children}</div>
        </div>
      </main>
      {toast ? (
        <Toast
          message={toast.message}
          {...(toast.actionLabel !== undefined ? { actionLabel: toast.actionLabel } : {})}
          {...(toast.action !== undefined ? { onAction: toast.action } : {})}
          onDismiss={store.dismissToast}
        />
      ) : null}
      {state.wl ? (
        <WorldLoader launch={state.wl} dec={state.dec} added={state.added} night={app.night} />
      ) : null}
      <BootSplash ready={ready} />
    </>
  );
}
