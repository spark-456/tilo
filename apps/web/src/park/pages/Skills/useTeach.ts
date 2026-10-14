// The "Teach Tilo something new" flow as one state machine (the reference's `startCapture`, `startRun`,
// `advance` and `save`): Show it, Tilo's version, Try run, Save, then saved. Every wait goes through the
// provider's `schedule` (never a timer of its own), one pending step at a time, cancelled when the state
// that wanted it changes or the page goes: a captured step and a run step each take 900 ms.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "../../api/index";
import type { Skill, SkillCapture, SkillVersion, Source, User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useSchedule } from "../../app/context";
import type { CurrencyCode } from "../../app/ledgerKpis";
import {
  CAPTURE_FIXTURE_EVENTS,
  CAPTURE_STEPS,
  DEFAULT_ASK,
  DEFAULT_DESC,
  LIVE_TEACH,
  type MethodKey,
  PLAN,
  SAVE_CODES,
  type Scope,
  TRY_RUN_FIXTURE_EVENTS,
  type Trigger,
  blankSkill,
  liveSavedOverride,
  savedOverride,
} from "./teachData";

export type Stage = 0 | 1 | 2 | 3;

export interface TeachInput {
  app: AppCtx;
  api: Api;
  user: User;
  /** The draft skill the flow turns into a learning one; none when the data holds no draft. */
  draft: Skill | undefined;
  /** Source of the loaded Skills data; fixture capture and try-run events only fire when source is "fixture". */
  source?: Source;
  /** Currency from the Ledger data. */
  currency?: CurrencyCode;
}

/** What every pane of the card gets. */
export interface PaneProps {
  t: Teach;
  night: boolean;
  user: User;
}

export interface Teach {
  source: Source;
  currency: CurrencyCode;
  stage: Stage;
  method: MethodKey;
  cap: number;
  rec: boolean;
  name: string;
  desc: string;
  ask: readonly boolean[];
  qAns: string | null;
  run: number;
  waiting: boolean;
  runDone: boolean;
  scope: Scope;
  trig: Trigger;
  saved: boolean;
  /** The skill this session saved (kept after "Teach another", as the reference keeps it). */
  taught: Skill | null;
  reach: readonly boolean[];
  /** SKILLS-5: a live page teaches by describing; these hold what the server answered. */
  live: boolean;
  busy: boolean;
  failure: string | null;
  steps: readonly string[];
  version: SkillVersion | null;
  setName: (v: string) => void;
  setDesc: (v: string) => void;
  setMethod: (k: MethodKey) => void;
  setScope: (s: Scope) => void;
  setTrig: (t: Trigger) => void;
  setQAns: (a: string) => void;
  toggleAsk: (i: number) => void;
  capture: () => void;
  goStep: (i: number) => void;
  next: () => void;
  back: () => void;
  approve: () => void;
  save: () => void;
  reset: () => void;
  view: () => void;
}

/** What the person is told when a capture or a version fails: unavailable, refused, or try again. */
const failureOf = (e: unknown): string => {
  const status = (e as { status?: unknown } | null)?.status;
  return status === 503
    ? LIVE_TEACH.unavailable
    : status === 422
      ? LIVE_TEACH.refused
      : LIVE_TEACH.retry;
};

/** Runs the call inside one promise, so a call that throws at once is a rejection like any other. */
const together = <T>(call: () => Promise<T>): Promise<T> =>
  new Promise((resolve) => resolve(call()));

export function useTeach({
  app,
  api,
  user,
  draft,
  source = "fixture",
  currency = "GBP",
}: TeachInput): Teach {
  const schedule = useSchedule();
  const isLive = source !== "fixture";
  const defaultName = isLive ? "" : (draft?.name ?? "");
  const [stage, setStage] = useState<Stage>(0);
  const [method, setMethodState] = useState<MethodKey>(isLive ? "describe" : "record");
  const [cap, setCap] = useState(0);
  const [rec, setRec] = useState(false);
  const [name, setName] = useState(defaultName);
  const [desc, setDesc] = useState(isLive ? "" : DEFAULT_DESC);
  const [ask, setAsk] = useState<readonly boolean[]>(DEFAULT_ASK);
  const [qAns, setQAns] = useState<string | null>(null);
  const [run, setRun] = useState(-1);
  const [waiting, setWaiting] = useState(false);
  const [runDone, setRunDone] = useState(false);
  // A live save takes only what POST /v1/skills accepts: a skill for the person that runs when they ask.
  const [scope, setScope] = useState<Scope>(isLive ? "me" : "team");
  const [trig, setTrig] = useState<Trigger>(isLive ? "ask" : "arrive");
  const [captured, setCaptured] = useState<SkillCapture | null>(null);
  const [version, setVersion] = useState<SkillVersion | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);
  const [saved, setSaved] = useState(false);
  const [taught, setTaught] = useState<Skill | null>(null);

  // A recording takes one fixture event at a time: never advances on a timer when source !== "fixture".
  useEffect(() => {
    if (!rec || source !== "fixture") return;
    const ev = CAPTURE_FIXTURE_EVENTS[method]?.[cap];
    if (!ev) return;
    return schedule(() => {
      if (cap + 1 >= CAPTURE_STEPS) {
        setCap(CAPTURE_STEPS);
        setRec(false);
      } else setCap(cap + 1);
    }, ev.delayMs);
  }, [rec, cap, method, source, schedule]);

  const advance = useCallback(() => {
    const n = run + 1;
    if (n >= PLAN.length) {
      setRun(PLAN.length);
      setRunDone(true);
    } else setRun(n);
    setWaiting(false);
  }, [run]);

  // The practice run advances only on fixture events; never advances on a timer pretending to work.
  useEffect(() => {
    if (stage !== 2 || run < 0 || run >= PLAN.length || waiting || runDone || source !== "fixture")
      return;
    const ev = TRY_RUN_FIXTURE_EVENTS[run];
    if (!ev) return;
    return schedule(() => {
      if (ask[run]) setWaiting(true);
      else advance();
    }, ev.delayMs);
  }, [stage, run, waiting, runDone, ask, advance, source, schedule]);

  const startRun = () => {
    setRun(0);
    setWaiting(false);
    setRunDone(false);
  };
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  /** One request at a time: a second click while one is out does nothing. */
  const once = (job: () => Promise<void>, fail: (e: unknown) => void) => {
    if (inflight.current) return;
    inflight.current = true;
    setBusy(true);
    setFailure(null);
    together(job)
      .catch((e: unknown) => {
        if (live.current) fail(e);
      })
      .finally(() => {
        inflight.current = false;
        if (live.current) setBusy(false);
      });
  };
  const failed = (e: unknown) => setFailure(failureOf(e));
  const describeIt = () => {
    const text = desc.trim();
    if (!text) return;
    setCaptured(null);
    setVersion(null);
    once(async () => {
      const r = await api.captureSkill(text);
      if (live.current) setCaptured(r.data);
    }, failed);
  };
  const proposeIt = () => {
    if (!captured) return;
    once(async () => {
      const r = await api.proposeVersion(captured.id);
      if (!live.current) return;
      setVersion(r.data);
      setAsk(r.data.steps.map((s) => s.ask));
      setStage(1);
    }, failed);
  };
  const saveLive = (nm: string) => {
    if (!version || !captured) return;
    const steps = version.steps.map((s, i) => ({ ...s, ask: s.locked || ask[i] === true }));
    const skill: Skill = {
      ...blankSkill(user.name),
      ...liveSavedOverride(user.name),
      name: nm,
      steps: steps.map((s) => s.text),
      draft: {
        scope,
        trigger: trig,
        plan: steps.map((s) => ({ text: s.text, tool: `${s.tool} · ${s.action}`, ask: s.ask })),
        server: { captured: captured.steps, question: version.question, steps },
      },
    };
    // Saved only once the server says so (a 201): nothing shows as saved before that.
    once(
      async () => {
        await api.saveSkill(skill);
        if (!live.current) return;
        setSaved(true);
        setTaught(skill);
        app.toast(LIVE_TEACH.saved(nm));
      },
      (e) => {
        const said = e instanceof Error ? e.message : "";
        const code = SAVE_CODES.has(said) ? said : null;
        app.toast(LIVE_TEACH.failed(nm, code));
      },
    );
  };

  const capture = () => {
    if (isLive) return describeIt();
    if (method === "describe" && !desc.trim()) return; // nothing to read: no steps from an empty box
    if (method === "describe" || method === "upload") {
      setCap(CAPTURE_STEPS);
      return;
    }
    setCap(0);
    setRec(true);
  };
  const reach = isLive
    ? [true, version !== null, false, version !== null] // no practice run live: step 3 stays locked
    : [true, cap >= CAPTURE_STEPS, cap >= CAPTURE_STEPS, runDone];
  const goTo = (i: Stage) => {
    if (isLive && !reach[i]) return;
    if (i === 2 && stage !== 2) startRun();
    setStage(i);
  };
  const reset = () => {
    setStage(0);
    setCap(0);
    setRec(false);
    setRun(-1);
    setWaiting(false);
    setRunDone(false);
    setSaved(false);
    setQAns(null);
    setName(defaultName);
    setCaptured(null);
    setVersion(null);
    setFailure(null);
    if (isLive) setDesc("");
  };

  const save = () => {
    const nm = name.trim();
    if (!nm) return; // a skill with no name cannot be told apart in the library
    if (isLive) return saveLive(nm);
    const skill: Skill = {
      ...(draft ?? blankSkill(user.name)),
      ...(source === "fixture" ? savedOverride(user.name) : liveSavedOverride(user.name)),
      name: nm,
      draft: {
        scope,
        trigger: trig,
        plan: PLAN.map((p, i) => ({ text: p.text, tool: p.tool, ask: ask[i] === true })),
      },
    };
    const before = taught;
    setSaved(true);
    setTaught(skill);
    app.toast(`Sample skill “${nm}” saved on this page only. Nothing is live or scheduled.`);
    together(() => api.saveSkill(skill)).catch(() => {
      if (!live.current) return;
      setSaved(false);
      setTaught(before);
      app.toast(`Couldn’t save “${nm}”. Try again`);
    });
  };

  return {
    source,
    currency,
    stage,
    method,
    cap,
    rec,
    name,
    desc,
    ask,
    qAns,
    run,
    waiting,
    runDone,
    scope,
    trig,
    saved,
    taught,
    reach,
    live: isLive,
    busy,
    failure,
    steps: captured?.steps ?? [],
    version,
    setName,
    setDesc,
    setMethod: (k) => {
      setMethodState(k);
      setCap(0);
      setRec(false);
    },
    setScope,
    setTrig,
    setQAns,
    toggleAsk: (i) => {
      if (isLive && version?.steps[i]?.locked !== false) return; // a step the server forced to ask stays on
      setAsk((a) => a.map((on, j) => (j === i ? !on : on)));
    },
    capture,
    goStep: (i) => goTo(i as Stage),
    next: () => {
      if (isLive && stage === 0) return proposeIt();
      goTo(Math.min(3, isLive && stage === 1 ? 3 : stage + 1) as Stage);
    },
    back: () => {
      setRun(-1);
      setWaiting(false);
      setRunDone(false);
      setStage(Math.max(0, isLive && stage === 3 ? 1 : stage - 1) as Stage);
    },
    approve: advance,
    save,
    reset,
    view: () => {
      if (taught) app.go("skills", { id: taught.id });
    },
  };
}
