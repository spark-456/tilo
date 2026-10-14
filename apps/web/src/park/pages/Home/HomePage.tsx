// The Home page (WEB-4): the greeting, the Today panel, the map pins and the composer, as drawn in
// design_handoff_tilo_web_app/design/Tilo App Home.dc.html. It floats panels over the city the shell draws
// behind it and has no landmark of its own. Data comes only through the Api (`useParkApi`); a page whose Api
// is not built shows "Not connected yet", never sample values. The composer's 900 ms goes through the
// provider's `useSchedule`, so a test never waits and a pending draft is cancelled when the page goes.
import { useEffect, useRef, useState } from "react";
import type {
  AgendaData,
  ApiResult,
  Decision,
  Effort,
  Ledger,
  TierKey,
  Today,
  User,
  World,
} from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { BUILD_SHA } from "../../app/buildStamp";
import { useDemoSession, useParkApi, useParkStore, useSchedule } from "../../app/context";
import { DEMO_START } from "../../app/store";
import { ComposerPanel, type Phase, QUICK_IDLE, type QuickView } from "./ComposerPanel";
import "./Home.css";
import { Hero, KpiStrip, Pins, TodayPanel } from "./Panels";
import { readEffort, writeEffort } from "./effortStore";
import {
  DRAFT_MS,
  INTAKE_MAX_CHARS,
  MODES,
  QUICK_MAX_CHARS,
  liveRows,
  liveSummaryLine,
  needsWorld,
  nextEvents,
  placedPins,
  spendOf,
  summaryLine,
} from "./homeData";
import { useComposerClearance } from "./useComposerClearance";

interface Base {
  user: User;
  today: Today;
  /** Null when the Api serves no calendar (live today): the Today panel then lists no events. */
  agenda: AgendaData | null;
  ledger: Ledger;
  /** What the "Waiting on you" tile says and opens; none when the Api serves no decisions. */
  decisions: Decision[];
  /** True when the decisions came from the live Api (an empty list is then "none open", not "unknown"). */
  decisionsServed: boolean;
}

type Loaded<T> = T | "failed" | null;

/** Runs the reads inside one promise, so a call that throws at once is a failed read like any other. */
const together = <T,>(reads: () => Promise<T>): Promise<T> =>
  new Promise((resolve) => resolve(reads()));
const data = <T,>(r: ApiResult<T>): T => r.data;

export function HomePage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const schedule = useSchedule();
  const store = useParkStore();
  // QA-DEMO-1: a demo session (the sample company) replays recorded data and starts no run.
  const demo = useDemoSession();
  const { go, dec, added, night, vw, vh, pins, needsLeft } = app;

  const [base, setBase] = useState<Loaded<Base>>(null);
  const [worlds, setWorlds] = useState<Loaded<World[]>>(null);
  // True once the worlds read came from the live Api: the composer works then, whatever the greeting reads did.
  const [worldsLive, setWorldsLive] = useState(false);

  useEffect(() => {
    let live = true;
    const decisions = (): Promise<{ list: Decision[]; served: boolean }> =>
      together(() => api.getDecisions()).then(
        (r) => ({ list: r.data, served: r.source === "live" }),
        () => ({ list: [], served: false }),
      );
    together(() =>
      Promise.all([
        api.getUser(),
        api.getToday(),
        api.getAgenda().catch((e: unknown) => {
          if (e instanceof Error && e.name === "NotBuilt") return null;
          throw e;
        }),
        api.getLedger(),
        decisions(),
      ]),
    ).then(
      ([user, today, agenda, ledger, decided]) => {
        if (live)
          setBase({
            user: data(user),
            today: data(today),
            agenda: agenda && data(agenda),
            ledger: data(ledger),
            decisions: decided.list,
            decisionsServed: decided.served,
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
        if (live) {
          setWorlds(data(r));
          setWorldsLive(r.source === "live");
        }
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

  // A start in flight (live only): the confirm control waits, nothing is cleared and nothing else is edited.
  const [sending, setSending] = useState(false);
  const sendingNow = useRef(false);
  // WEB-W1: files picked or pasted for the next Thinking start. They leave with Start on the one POST /intake.
  const [files, setFiles] = useState<File[]>([]);
  const confirmStart = () => {
    if (sendingNow.current) return;
    const text = query.trim();
    if (demo) {
      // HR-1: no world, no progress and no "Director read your brief" without a recorded event. Say so plainly
      // and open the sample world, whose data is labelled Sample.
      store.toast(DEMO_START);
      toIdle();
      if (waitingIn) go("world", { id: waitingIn.id });
      else go("worlds");
      return;
    }
    if (!store.getState().sources.live) {
      app.addWorld(modeKey, text);
      setQuery("");
      toIdle();
      return;
    }
    if (text === "") {
      // Issue 932: the plan on show is the example for an empty box; sending it would post nothing to the server.
      store.toast("Describe your task first, then press Start.");
      return;
    }
    sendingNow.current = true;
    setSending(true);
    store.startWorld(modeKey, text, files).then((ok) => {
      sendingNow.current = false;
      setSending(false);
      // A8: the confirm button was disabled while the call ran, so focus fell to the page; it goes back to the
      // button to try again, or to the task box once the start is done.
      if (!ok) {
        setRefocus("confirm"); // the card stays open and the text stays, so the person can try again
        return;
      }
      setQuery("");
      setFiles([]);
      toIdle();
      setRefocus("input");
    });
  };
  const composerInput = useRef<HTMLInputElement>(null);
  const [refocus, setRefocus] = useState<"confirm" | "input" | null>(null);
  useEffect(() => {
    if (refocus === null) return;
    const el =
      refocus === "input"
        ? composerInput.current
        : root.current?.querySelector<HTMLElement>(".park-home-confirm");
    el?.focus();
    setRefocus(null);
  }, [refocus]);
  // A3: "Change brief" puts the person back in the task box, ready to edit.
  const changeBrief = () => {
    if (sendingNow.current) return;
    toIdle();
    composerInput.current?.focus();
  };
  // A3: Esc closes the plan card (and the drafting line) the same way, unless the start is already on its way.
  const toIdleNow = useRef(toIdle);
  toIdleNow.current = toIdle;
  useEffect(() => {
    if (phase === "idle") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || sendingNow.current) return;
      toIdleNow.current();
      composerInput.current?.focus();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [phase]);

  // Quick / Thinking (COST-FAST-1). The choice is remembered per signed-in email (effortStore), Thinking by
  // default. A Quick ask makes no world and no plan: the answer, or the offer to switch, shows in the composer.
  const [effort, setEffort] = useState<Effort>(() => readEffort());
  const email = base !== null && base !== "failed" ? base.user.email : null;
  // Once the signed-in email is known, that person's remembered choice applies, unless they have chosen since.
  const chosenNow = useRef(false);
  useEffect(() => {
    if (email && !chosenNow.current) setEffort(readEffort(email));
  }, [email]);
  const [quick, setQuick] = useState<QuickView>(QUICK_IDLE);
  const asking = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const busy = () => sendingNow.current || asking.current;
  const chooseEffort = (next: Effort) => {
    if (busy()) return;
    chosenNow.current = true;
    setEffort(next);
    writeEffort(email, next);
    setQuick(QUICK_IDLE);
    toIdle();
  };
  const ask = () => {
    if (busy()) return;
    const text = query.trim();
    if (text === "") {
      setQuick({ state: "error", message: "Type your question first." });
      return;
    }
    const length = Array.from(text).length;
    if (length > QUICK_MAX_CHARS) {
      setQuick({
        state: "error",
        message: `A Quick question can be up to ${QUICK_MAX_CHARS} characters; this one is ${length}. Shorten it, or switch to Thinking.`,
      });
      return;
    }
    asking.current = true;
    setQuick({ state: "asking" });
    store.askQuick(modeKey, text).then((out) => {
      asking.current = false;
      if (!alive.current) return;
      setQuick(
        out.kind === "answered"
          ? { state: "answered", text: out.text, cost: out.cost, sample: out.sample }
          : out.kind === "switch"
            ? { state: "switch", reason: out.reason }
            : { state: "error", message: out.message },
      );
    });
  };
  // "Switch to Thinking" on an offer: the same text goes as Thinking, through the usual start.
  const switchToThinking = () => {
    if (busy()) return;
    chosenNow.current = true;
    setEffort("thinking");
    writeEffort(email, "thinking");
    setQuick(QUICK_IDLE);
    confirmStart();
  };

  const open = (id: string) => go("world", { id });
  const failed = base === "failed" || worlds === "failed";
  const ready = base !== null && base !== "failed" && worlds !== null && worlds !== "failed";
  const waitingIn = ready ? needsWorld(worlds) : undefined;
  // Live (PRD 9.4): numbers come only from the served worlds and served decisions, never the sample count.
  const served = ready && worldsLive;
  const openServed =
    ready && base.decisionsServed ? base.decisions.filter((d) => !dec[d.k]).length : null;
  const needs = served ? (openServed ?? 0) : needsLeft;
  const summary = served
    ? liveSummaryLine(
        worlds.filter((w) => !w.isNew && (w.st === "running" || w.st === "needs")).length,
        openServed,
      )
    : summaryLine(needs, night);

  const root = useRef<HTMLDivElement>(null);
  const composerShown = !failed || (worldsLive && worlds !== "failed");
  useComposerClearance(root, composerShown);

  return (
    <div ref={root} className="park-home-root" data-testid="park-page-home">
      {ready ? (
        <>
          <Pins
            pins={placedPins(pins, worlds, needs, night, vw || 1440, vh || 900, served)}
            onOpen={open}
          />
          <div className="park-home-leftcol">
            <Hero
              dateLine={`${base.today.long}${night ? " · 21:10" : ""}`.toUpperCase()}
              greeting={`${night ? "Good evening" : "Good morning"}, ${base.user.first}.`}
              summary={summary}
              needs={needs}
              needsKnown={!served || openServed !== null}
              night={night}
              worldName={waitingIn?.name ?? null}
              onReview={() => (waitingIn ? open(waitingIn.id) : go("worlds"))}
            />
            <KpiStrip
              ledger={base.ledger}
              dec={dec}
              decisions={base.decisions}
              fallbackWorld={waitingIn?.id}
              onWorld={open}
            />
          </div>
          <TodayPanel
            served={served}
            rows={liveRows(worlds, needs, served)}
            sample={served ? worlds.find((w) => w.sample) : undefined}
            events={base.agenda && base.agenda.days !== null ? nextEvents(base.agenda) : []}
            spend={spendOf(base.ledger)}
            night={night}
            onWorld={open}
            onWorlds={() => go("worlds")}
            onAgenda={() => go("agenda")}
            onLedger={() => go("ledger")}
          />
        </>
      ) : null}
      {failed ? (
        <div className="park-home-hero park-home-glass">
          <h1 className="park-home-h1">Home</h1>
          <p className="park-home-summary">Not connected yet</p>
        </div>
      ) : null}
      {composerShown ? (
        <ComposerPanel
          sending={sending}
          sample={demo}
          compact={vw > 0 && vw <= 480}
          inputRef={composerInput}
          maxLength={INTAKE_MAX_CHARS}
          staging={{
            files,
            onChange: setFiles,
            disabledReason: demo
              ? "Uploads are off in the demo; sign in to attach files."
              : !worldsLive
                ? "Uploads need setup; the owner has not finished it."
                : effort === "quick"
                  ? "Uploads work with Thinking tasks; a Quick ask makes no task."
                  : null,
          }}
          mode={mode}
          modes={MODES}
          query={query}
          shown={query.trim() || mode.example}
          phase={phase}
          effort={effort}
          onEffort={chooseEffort}
          quick={quick}
          onSwitch={switchToThinking}
          onQuery={(value) => {
            if (busy()) return;
            setQuery(value);
            setQuick(QUICK_IDLE);
            toIdle();
          }}
          onMode={(key) => {
            if (busy()) return;
            setModeKey(key as TierKey);
            setQuick(QUICK_IDLE);
            toIdle();
          }}
          onChip={(label) => {
            if (busy()) return;
            setQuery(label);
            setQuick(QUICK_IDLE);
            toIdle();
          }}
          onDraft={effort === "quick" ? ask : draft}
          onConfirm={confirmStart}
          onChange={changeBrief}
        />
      ) : null}
      <nav className="park-home-legal" aria-label="Legal">
        <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a> ·{" "}
        <span className="park-home-build" title="The commit this page was built from">
          Build {BUILD_SHA}
        </span>
      </nav>
    </div>
  );
}
