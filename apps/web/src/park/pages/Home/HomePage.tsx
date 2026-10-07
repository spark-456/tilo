// The Home page (WEB-4): the greeting, the Today panel, the map pins and the composer, as drawn in
// design_handoff_tilo_web_app/design/Tilo App Home.dc.html. It floats panels over the city the shell draws
// behind it and has no landmark of its own. Data comes only through the Api (`useParkApi`); a page whose Api
// is not built shows "Not connected yet", never sample values. The composer's 900 ms goes through the
// provider's `useSchedule`, so a test never waits and a pending draft is cancelled when the page goes.
import { useEffect, useRef, useState } from "react";
import type {
  Agenda,
  ApiResult,
  Decision,
  Ledger,
  TierKey,
  Today,
  User,
  World,
} from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi, useSchedule } from "../../app/context";
import { ComposerPanel, type Phase } from "./ComposerPanel";
import "./Home.css";
import { Hero, KpiStrip, Pins, TodayPanel } from "./Panels";
import {
  DRAFT_MS,
  MODES,
  liveRows,
  needsWorld,
  nextEvents,
  placedPins,
  spendOf,
  summaryLine,
} from "./homeData";

interface Base {
  user: User;
  today: Today;
  agenda: Agenda;
  ledger: Ledger;
  /** What the "Waiting on you" tile says and opens; none when the Api serves no decisions. */
  decisions: Decision[];
}

type Loaded<T> = T | "failed" | null;

/** Runs the reads inside one promise, so a call that throws at once is a failed read like any other. */
const together = <T,>(reads: () => Promise<T>): Promise<T> =>
  new Promise((resolve) => resolve(reads()));
const data = <T,>(r: ApiResult<T>): T => r.data;

export function HomePage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const schedule = useSchedule();
  const { go, dec, added, night, vw, vh, pins, needsLeft: needs } = app;

  const [base, setBase] = useState<Loaded<Base>>(null);
  const [worlds, setWorlds] = useState<Loaded<World[]>>(null);

  useEffect(() => {
    let live = true;
    const decisions = (): Promise<Decision[]> =>
      together(() => api.getDecisions()).then(data, () => []);
    together(() =>
      Promise.all([api.getUser(), api.getToday(), api.getAgenda(), api.getLedger(), decisions()]),
    ).then(
      ([user, today, agenda, ledger, decided]) => {
        if (live)
          setBase({
            user: data(user),
            today: data(today),
            agenda: data(agenda),
            ledger: data(ledger),
            decisions: decided,
          });
      },
      () => {
        if (live) setBase("failed");
      },
    );
    return () => {
      live = false;
    };
  }, [api]);

  // The worlds depend on the decisions taken and the worlds started; the old list stays until the new one lands.
  useEffect(() => {
    let live = true;
    together(() => api.getWorlds(dec, added)).then(
      (r) => {
        if (live) setWorlds(data(r));
      },
      () => {
        if (live) setWorlds("failed");
      },
    );
    return () => {
      live = false;
    };
  }, [api, dec, added]);

  // The composer: { size, text, phase } of the reference.
  const [modeKey, setModeKey] = useState<TierKey>("quick");
  const [query, setQuery] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const phaseNow = useRef<Phase>("idle");
  const pending = useRef<(() => void) | null>(null);
  const settle = (next: Phase) => {
    phaseNow.current = next;
    setPhase(next);
  };
  const cancelDraft = () => {
    pending.current?.();
    pending.current = null;
  };
  useEffect(
    () => () => {
      pending.current?.();
      pending.current = null;
    },
    [],
  );
  const toIdle = () => {
    cancelDraft();
    settle("idle");
  };
  const draft = () => {
    if (phaseNow.current !== "idle") return;
    cancelDraft();
    settle("drafting");
    pending.current = schedule(() => {
      pending.current = null;
      settle("plan");
    }, DRAFT_MS);
  };
  const mode = MODES.find((m) => m.key === modeKey) ?? MODES[0];

  const open = (id: string) => go("world", { id });
  const failed = base === "failed" || worlds === "failed";
  const ready = base !== null && base !== "failed" && worlds !== null && worlds !== "failed";
  const waitingIn = ready ? needsWorld(worlds) : undefined;

  return (
    <div className="park-home-root" data-testid="park-page-home">
      {ready ? (
        <>
          <Pins
            pins={placedPins(pins, worlds, needs, night, vw || 1440, vh || 900)}
            onOpen={open}
          />
          <Hero
            dateLine={`${base.today.long}${night ? " · 21:10" : ""}`.toUpperCase()}
            greeting={`${night ? "Good evening" : "Good morning"}, ${base.user.first}.`}
            summary={summaryLine(needs, night)}
            needs={needs}
            night={night}
            worldName={waitingIn?.name ?? null}
            onReview={() => (waitingIn ? open(waitingIn.id) : go("worlds"))}
          />
          {(vw || 1440) >= 1180 ? (
            <KpiStrip
              ledger={base.ledger}
              dec={dec}
              decisions={base.decisions}
              fallbackWorld={waitingIn?.id}
              onWorld={open}
            />
          ) : null}
          {(vw || 1440) >= 1180 ? (
            <TodayPanel
              rows={liveRows(worlds, needs)}
              events={nextEvents(base.agenda)}
              spend={spendOf(base.ledger)}
              night={night}
              onWorld={open}
              onWorlds={() => go("worlds")}
              onAgenda={() => go("agenda")}
              onLedger={() => go("ledger")}
            />
          ) : null}
        </>
      ) : null}
      {failed ? (
        <div className="park-home-hero park-home-glass">
          <h1 className="park-home-h1">Home</h1>
          <p className="park-home-summary">Not connected yet</p>
        </div>
      ) : (
        <ComposerPanel
          mode={mode}
          modes={MODES}
          query={query}
          shown={query.trim() || mode.example}
          phase={phase}
          onQuery={(value) => {
            setQuery(value);
            toIdle();
          }}
          onMode={(key) => {
            setModeKey(key as TierKey);
            toIdle();
          }}
          onChip={(label) => {
            setQuery(label);
            toIdle();
          }}
          onDraft={draft}
          onConfirm={() => {
            app.addWorld(modeKey, query.trim());
            setQuery("");
            toIdle();
          }}
          onChange={toIdle}
        />
      )}
    </div>
  );
}
