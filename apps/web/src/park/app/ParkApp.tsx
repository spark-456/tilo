// THROWAWAY (WEB-3b validation only): stand-in for ParkApp (3a) wearing the shell (3b).
import { Suspense, useEffect, useRef } from "react";
import "../tokens/park.css";
import "../components/park.components.css";
import { AppShell } from "../shell/AppShell";
import { ParkProvider, useApp } from "./context";
import { PAGES } from "./pages";

const TITLE: Record<string, string> = {
  home: "Home",
  worlds: "Worlds",
  world: "World",
  skills: "Skills",
  ledger: "Ledger",
  agenda: "Agenda",
  team: "Team",
  profile: "Profile",
  connectors: "Connectors",
};

function Inner({ known }: { known: boolean }) {
  const app = useApp();
  const Page = PAGES[app.page];
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    document.title = `${known ? (TITLE[app.page] ?? "") : "Page not found"} · Tilo`;
    ref.current?.querySelector("h1")?.focus();
  }, [app.page, known, app.params]);
  return (
    <div data-park="" data-time={app.time}>
      <AppShell>
        <div ref={ref}>
          {known ? (
            <Suspense fallback={null}>
              <Page app={app} />
            </Suspense>
          ) : (
            <section data-testid="park-not-found">
              <h1 tabIndex={-1}>Page not found</h1>
              <a href="/park/home">Home</a>
            </section>
          )}
        </div>
      </AppShell>
    </div>
  );
}

function Gate() {
  const app = useApp();
  void app;
  const known = window.location.pathname !== "/park/nope";
  return <Inner known={known} />;
}

export function ParkApp() {
  return (
    <ParkProvider>
      <Gate />
    </ParkProvider>
  );
}
export default ParkApp;
