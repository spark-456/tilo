// The Teach wizard's flow as one state machine (STUDIO-4: Describe it, Show an example, Review the steps). Stage 0 is
// steps 1 and 2 (the description and what Tilo read from it), stage 1 is step 3 (Tilo's version and Save). Live, each
// step is one request at a time (POST /v1/skills/captures, .../{id}/version, POST /v1/skills) and only the server's
// answer moves the flow on. On sample data the description is read at once and Save is this page's only. There is no
// practice run and no recording: neither has a route, and nothing here waits on a timer (HR-1..7).
import { useEffect, useRef, useState } from "react";
import { displayApiError } from "../../api/errorMessage";
import type { Api } from "../../api/index";
import { teamsClient } from "../../api/selfServeTeams";
import type { Skill, SkillCapture, SkillVersion, Source, User } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import type { CurrencyCode } from "../../app/ledgerKpis";
import {
  CAPTURE_STEPS,
  DEFAULT_ASK,
  DEFAULT_DESC,
  LIVE_TEACH,
  PLAN,
  type Scope,
  type Trigger,
  blankSkill,
  liveSavedOverride,
  savedOverride,
} from "./teachData";

export type Stage = 0 | 1;

export interface TeachInput {
  app: AppCtx;
  api: Api;
  user: User;
  /** The draft skill the flow turns into a learning one; none when the data holds no draft. */
  draft: Skill | undefined;
  /** Source of the loaded Skills data: a live page posts, a sample one does not. */
  source?: Source;
  /** Currency from the Ledger data. */
  currency?: CurrencyCode;
}

export interface Teach {
  source: Source;
  currency: CurrencyCode;
  stage: Stage;
  /** Sample data: how many steps were read from the description (CAPTURE_STEPS once read). */
  cap: number;
  name: string;
  desc: string;
  ask: readonly boolean[];
  qAns: string | null;
  scope: Scope;
  teamId: string | null;
  teams: readonly string[] | null;
  hosts: readonly string[];
  trig: Trigger;
  saved: boolean;
  /** The skill this session saved (kept after "Teach another"). */
  taught: Skill | null;
  live: boolean;
  busy: boolean;
  failure: unknown;
  /** Live: the steps the server read out of the description. */
  steps: readonly string[];
  version: SkillVersion | null;
  setName: (v: string) => void;
  setDesc: (v: string) => void;
  setScope: (s: Scope) => void;
  loadTeams: () => void;
  chooseTeam: (id: string) => void;
  removeHost: (host: string) => void;
  setTrig: (t: Trigger) => void;
  setQAns: (a: string) => void;
  toggleAsk: (i: number) => void;
  capture: () => void;
  next: () => void;
  back: () => void;
  save: () => void;
  reset: () => void;
}

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
  const isLive = source !== "fixture";
  const defaultName = isLive ? "" : (draft?.name ?? "");
  const [stage, setStage] = useState<Stage>(0);
  const [cap, setCap] = useState(0);
  const [name, setName] = useState(defaultName);
  const [desc, setDesc] = useState(isLive ? "" : DEFAULT_DESC);
  const [ask, setAsk] = useState<readonly boolean[]>(DEFAULT_ASK);
  const [qAns, setQAns] = useState<string | null>(null);
  // A live save takes only what POST /v1/skills accepts: a skill for the person that runs when they ask.
  const [scope, setScope] = useState<Scope>(isLive ? "me" : "team");
  const [teamId, setTeamId] = useState<string | null>(null);
  const [teams, setTeams] = useState<readonly string[] | null>(null);
  const [hosts, setHosts] = useState<string[]>([]);
  const [trig, setTrig] = useState<Trigger>(isLive ? "ask" : "arrive");
  const [captured, setCaptured] = useState<SkillCapture | null>(null);
  const [version, setVersion] = useState<SkillVersion | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const inflight = useRef(false);
  const [saved, setSaved] = useState(false);
  const [taught, setTaught] = useState<Skill | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
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
        if (mounted.current) fail(e);
      })
      .finally(() => {
        inflight.current = false;
        if (mounted.current) setBusy(false);
      });
  };
  const failed = (e: unknown) => setFailure(e);
  const describeIt = () => {
    const text = desc.trim();
    if (!text) return;
    setCaptured(null);
    setVersion(null);
    once(async () => {
      const r = await api.captureSkill(text);
      setCaptured(r.data);
    }, failed);
  };
  const proposeIt = () => {
    if (!captured) return;
    once(async () => {
      const r = await api.proposeVersion(captured.id);
      setVersion(r.data);
      setHosts(r.data.hosts);
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
        teamId,
        trigger: trig,
        plan: steps.map((s) => ({ text: s.text, tool: `${s.tool} · ${s.action}`, ask: s.ask })),
        server: {
          captured: captured.steps,
          question: version.question,
          steps,
          inputs: version.inputs,
          hosts,
        },
      },
    };
    // Saved only once the server says so (a 201): nothing shows as saved before that.
    once(
      async () => {
        await api.saveSkill(skill);
        setSaved(true);
        setTaught(skill);
        app.toast(LIVE_TEACH.saved(nm));
      },
      (e) => {
        setFailure(e);
        app.toast(`Couldn’t save “${nm}”. ${displayApiError(e)}`);
      },
    );
  };

  const capture = () => {
    if (isLive) return describeIt();
    if (desc.trim()) setCap(CAPTURE_STEPS); // nothing to read: no steps from an empty box
  };
  const reset = () => {
    setStage(0);
    setCap(0);
    setSaved(false);
    setQAns(null);
    setName(defaultName);
    setCaptured(null);
    setVersion(null);
    setHosts([]);
    setTeams(null);
    setTeamId(null);
    setFailure(null);
    if (isLive) setDesc("");
  };

  const save = () => {
    const nm = name.trim();
    if (!nm) return; // a skill with no name cannot be told apart in the library
    if (isLive) return saveLive(nm);
    const skill: Skill = {
      ...(draft ?? blankSkill(user.name)),
      ...savedOverride(user.name),
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
      if (!mounted.current) return;
      setSaved(false);
      setTaught(before);
      app.toast(`Couldn’t save “${nm}”. Try again`);
    });
  };

  return {
    source,
    currency,
    stage,
    cap,
    name,
    desc,
    ask,
    qAns,
    scope,
    teamId,
    teams,
    hosts,
    trig,
    saved,
    taught,
    live: isLive,
    busy,
    failure,
    steps: captured?.steps ?? [],
    version,
    setName,
    setDesc,
    setScope,
    loadTeams: () => {
      const client = teamsClient();
      if (!isLive || !client) return;
      client.mine().then(
        ({ teams: rows }) => {
          if (mounted.current)
            setTeams(rows.filter((row) => row.state === "member").map((row) => row.team));
        },
        (e: unknown) => {
          if (mounted.current) setFailure(e);
        },
      );
    },
    chooseTeam: (id) => {
      if (teams?.includes(id)) {
        setTeamId(id);
        setScope("team");
      }
    },
    removeHost: (host) => setHosts((current) => current.filter((item) => item !== host)),
    setTrig,
    setQAns,
    toggleAsk: (i) => {
      if (isLive && version?.steps[i]?.locked !== false) return; // a step the server forced to ask stays on
      setAsk((a) => a.map((on, j) => (j === i ? !on : on)));
    },
    capture,
    next: () => {
      if (isLive) return proposeIt();
      if (cap >= CAPTURE_STEPS) setStage(1);
    },
    back: () => setStage(0),
    save,
    reset,
  };
}
