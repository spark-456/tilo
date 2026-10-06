// The "Teach Tilo something new" flow as one state machine (the reference's `startCapture`, `startRun`,
// `advance` and `save`): Show it, Tilo's version, Try run, Save, then saved. Every wait goes through the
// provider's `schedule` (never a timer of its own), one pending step at a time, cancelled when the state
// that wanted it changes or the page goes: a captured step and a run step each take 900 ms.
import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "../../api/index";
import type { Skill, User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useSchedule } from "../../app/context";
import {
  CAPTURE_STEPS,
  DEFAULT_ASK,
  DEFAULT_DESC,
  type MethodKey,
  PLAN,
  STEP_MS,
  type Scope,
  type Trigger,
  blankSkill,
  savedOverride,
} from "./teachData";

export type Stage = 0 | 1 | 2 | 3;

export interface TeachInput {
  app: AppCtx;
  api: Api;
  user: User;
  /** The draft skill the flow turns into a learning one; none when the data holds no draft. */
  draft: Skill | undefined;
}

/** What every pane of the card gets. */
export interface PaneProps {
  t: Teach;
  night: boolean;
  user: User;
}

export interface Teach {
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

/** Runs the call inside one promise, so a call that throws at once is a rejection like any other. */
const together = <T>(call: () => Promise<T>): Promise<T> =>
  new Promise((resolve) => resolve(call()));

export function useTeach({ app, api, user, draft }: TeachInput): Teach {
  const schedule = useSchedule();
  const defaultName = draft?.name ?? "";
  const [stage, setStage] = useState<Stage>(0);
  const [method, setMethodState] = useState<MethodKey>("record");
  const [cap, setCap] = useState(0);
  const [rec, setRec] = useState(false);
  const [name, setName] = useState(defaultName);
  const [desc, setDesc] = useState(DEFAULT_DESC);
  const [ask, setAsk] = useState<readonly boolean[]>(DEFAULT_ASK);
  const [qAns, setQAns] = useState<string | null>(null);
  const [run, setRun] = useState(-1);
  const [waiting, setWaiting] = useState(false);
  const [runDone, setRunDone] = useState(false);
  const [scope, setScope] = useState<Scope>("team");
  const [trig, setTrig] = useState<Trigger>("arrive");
  const [saved, setSaved] = useState(false);
  const [taught, setTaught] = useState<Skill | null>(null);

  // A recording takes a step at a time: one pending wait, replaced whenever `rec` or `cap` changes.
  useEffect(() => {
    if (!rec) return;
    return schedule(() => {
      if (cap + 1 >= CAPTURE_STEPS) {
        setCap(CAPTURE_STEPS);
        setRec(false);
      } else setCap(cap + 1);
    }, STEP_MS);
  }, [rec, cap, schedule]);

  const advance = useCallback(() => {
    const n = run + 1;
    if (n >= PLAN.length) {
      setRun(PLAN.length);
      setRunDone(true);
    } else setRun(n);
    setWaiting(false);
  }, [run]);

  // The practice run: a step every 900 ms; a step set to ask first stops it until the person answers.
  useEffect(() => {
    if (stage !== 2 || run < 0 || run >= PLAN.length || waiting || runDone) return;
    return schedule(() => {
      if (ask[run]) setWaiting(true);
      else advance();
    }, STEP_MS);
  }, [stage, run, waiting, runDone, ask, advance, schedule]);

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

  const capture = () => {
    if (method === "describe" || method === "upload") {
      setCap(CAPTURE_STEPS);
      return;
    }
    setCap(0);
    setRec(true);
  };
  const goTo = (i: Stage) => {
    if (i === 2 && stage !== 2) startRun();
    setStage(i);
  };
  const reach = [true, cap >= CAPTURE_STEPS, cap >= CAPTURE_STEPS, runDone];
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
  };

  const save = () => {
    const nm = name.trim();
    if (!nm) return; // a skill with no name cannot be told apart in the library
    const skill: Skill = {
      ...(draft ?? blankSkill(user.name)),
      ...savedOverride(user.name),
      name: nm,
    };
    const before = taught;
    setSaved(true);
    setTaught(skill);
    app.toast(`Saved “${nm}”. It’s live for ${scope === "me" ? "you" : "the team"}`);
    together(() => api.saveSkill(skill)).catch(() => {
      if (!live.current) return;
      setSaved(false);
      setTaught(before);
      app.toast(`Couldn’t save “${nm}”. Try again`);
    });
  };

  return {
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
    toggleAsk: (i) => setAsk((a) => a.map((on, j) => (j === i ? !on : on))),
    capture,
    goStep: (i) => goTo(i as Stage),
    next: () => goTo(Math.min(3, stage + 1) as Stage),
    back: () => {
      setRun(-1);
      setWaiting(false);
      setRunDone(false);
      setStage(Math.max(0, stage - 1) as Stage);
    },
    approve: advance,
    save,
    reset,
    view: () => {
      if (taught) app.go("skills", { id: taught.id });
    },
  };
}
