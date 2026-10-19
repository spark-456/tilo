import { useSyncExternalStore } from "react";
import { session } from "../auth/session";
import { useApp } from "../park/app/context";
import { useFirstRun } from "../park/sample/useFirstRun";
import { OnboardingLayer, autoShowAllowed } from "./OnboardingLayer";
import { PageTourLayer } from "./PageTourLayer";
import { userKeyOf } from "./storage";

export default function FirstRunTourLayer() {
  const app = useApp();
  const firstRun = useFirstRun();
  const identity = useSyncExternalStore(session.subscribe, session.getState, session.getState);
  return firstRun === true ? (
    <PageTourLayer
      page={app.page}
      firstRun
      autoInvite={autoShowAllowed()}
      userKey={userKeyOf(identity)}
    />
  ) : (
    <OnboardingLayer enabled={false} />
  );
}
