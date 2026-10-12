// FR-CHN-17d: "Browser notifications" in the Notifications tab. It renders only for a live, signed-in Google session
// (`livePushFlow()` is null in the fixture world and in a demo, so nothing here runs there), is off by default, and
// the person turns it on. The words say what is true: a stored browser sends nothing until the owner's push policy
// exists (tilo-api's `delivery`), and a browser that says no stays off.
import { useEffect, useMemo, useState } from "react";
import type { PushFlow, PushProblem, PushView } from "../../../api/push";
import { livePushFlow } from "../../../api/pushEnv";
import { Switch } from "../../components";

const TEXT = {
  checking: "Checking this browser.",
  off: "Off. Turn on to let this browser show a notice when something needs you.",
  waiting:
    "On for this browser, but nothing is sent yet: notices stay off until the owner's push policy exists.",
  ready: "On for this browser.",
  unsupported: "This browser cannot show notifications.",
  denied:
    "This browser blocked notifications. Allow them in the browser's site settings, then try again.",
  not_configured: "Browser notifications are not set up on this deployment yet.",
  failed: "Tilo could not change this. Nothing was saved, so please try again.",
} as const;

function words(view: PushView | null, problem: PushProblem | null): string {
  if (problem) return TEXT[problem];
  if (view === null) return TEXT.checking;
  if (view.permission === "unsupported") return TEXT.unsupported;
  if (view.permission === "denied" && !view.here) return TEXT.denied;
  if (!view.here) return TEXT.off;
  return view.state?.delivery === "ready" ? TEXT.ready : TEXT.waiting;
}

function PushRow({ flow }: { flow: PushFlow }) {
  const [view, setView] = useState<PushView | null>(null);
  const [problem, setProblem] = useState<PushProblem | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    flow.read().then((v) => live && setView(v));
    return () => {
      live = false;
    };
  }, [flow]);

  const change = async (on: boolean) => {
    setBusy(true);
    setProblem(null);
    const result = await (on ? flow.enable() : flow.disable());
    if (!result.ok) setProblem(result.problem);
    setView(await flow.read());
    setBusy(false);
  };
  const unavailable = view?.permission === "unsupported";
  return (
    <div className="park-profile-quiet">
      <div className="park-profile-grow">
        <div className="park-profile-mlabel">Browser notifications</div>
        <div className="park-profile-msub" aria-live="polite">
          {words(view, problem)}
        </div>
      </div>
      <Switch
        label="Browser notifications"
        checked={view?.here ?? false}
        disabled={busy || view === null || unavailable}
        onChange={change}
      />
    </div>
  );
}

/** `flow` is for tests: undefined means the deployment's own flow (null in the fixture world and in a demo). */
export function PushControl({ flow }: { flow?: PushFlow | null }) {
  const live = useMemo(() => (flow === undefined ? livePushFlow() : flow), [flow]);
  return live ? <PushRow flow={live} /> : null;
}
