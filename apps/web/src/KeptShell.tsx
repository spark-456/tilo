// UI-10 W21: shared mount boundary; Park never imports the kept screens.
import type { ReactNode } from "react";
import { ParkProvider, useApp, useSessionAuth } from "./park/app/context";
import { AppShell } from "./park/shell/AppShell";
import { ParkAuthProvider } from "./park/shell/auth";
import { themeFor } from "./park/tokens/themes";
import "./park/tokens/park.css";
import "./park/tokens/themes.css";
import "./kept-shell.css";

function Shell({ children }: { children: ReactNode }) {
  const app = useApp();
  return (
    <div
      data-park
      data-kept-shell
      data-time={app.time}
      data-motion={app.motion}
      data-theme={themeFor(app.prefs.theme)}
    >
      <AppShell>{children}</AppShell>
    </div>
  );
}

export function KeptShell({ children }: { children: ReactNode }) {
  const auth = useSessionAuth();
  return (
    <ParkProvider>
      <ParkAuthProvider auth={auth}>
        <Shell>{children}</Shell>
      </ParkAuthProvider>
    </ParkProvider>
  );
}
