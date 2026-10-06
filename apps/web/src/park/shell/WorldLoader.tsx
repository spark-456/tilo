// THROWAWAY (WEB-3b validation only).
import type { ReactNode } from "react";
import { useSyncExternalStore } from "react";
import { worlds } from "../api/fixtures/worlds";
import { useApp, useParkStore } from "../app/context";
import { getKit } from "./kit";

const STEPS = {
  City: (n: number) => ["Loading districts and buildings", `Waking ${n} agents`, "Syncing spend and decisions"],
  Town: () => ["Loading the routine", "Reading run history", "Checking the next run"],
  Village: () => ["Loading the task", "Checking progress", "Fetching results"],
} as const;

export function WorldLoader() {
  const app = useApp();
  const store = useParkStore();
  const s = useSyncExternalStore(store.subscribe, store.getState);
  if (!s.wl) return null;
  const w = worlds(s.dec, [...s.added]).find((x) => x.id === s.wl?.id);
  if (!w) return null;
  const step = s.wl.step;
  const K = getKit();
  const art: ReactNode =
    w.tier === "City"
      ? (K.agent({ rank: "director", expr: "focused" }, 50, app.night) as ReactNode)
      : (K.art(w, 50, app.night) as ReactNode);
  const labels = w.tier === "City" ? STEPS.City(w.agents) : STEPS[w.tier]();
  return (
    <div className="park-wl" data-testid="world-loader" role="status" aria-live="polite">
      <div className="park-wl__card">
        <div className="park-wl__top">
          <div className="park-wl__art">{art}</div>
          <div className="park-wl__text">
            <div className="park-wl__eyebrow">{`OPENING ${w.tier}`.toUpperCase()}</div>
            <div className="park-wl__name">{w.name}</div>
            <div className="park-wl__meta">{`${w.tool} · ${w.agents} ${w.agents === 1 ? "agent" : "agents"}`}</div>
          </div>
        </div>
        <div className="park-wl__steps">
          {labels.map((label, i) => {
            const st = i < step ? "done" : i === step ? "active" : "pending";
            return (
              <div key={label} className={`park-wl__step park-wl__step--${st}`} data-state={st}>
                <span className={`park-wl__tick park-wl__tick--${st}`}>
                  {st === "done" ? getKit().icon("check", 12) as ReactNode : st === "active" ? <span className="park-wl__spin" /> : null}
                </span>
                {label}
              </div>
            );
          })}
        </div>
        <div className="park-wl__track">
          <div className="park-wl__fill" style={{ width: `${Math.min(100, (step + 1) * 30)}%` }} />
        </div>
      </div>
    </div>
  );
}
