import { useSyncExternalStore } from "react";
import { session } from "../auth/session";
import { useApp } from "../park/app/context";
import { OnboardingLayer } from "./OnboardingLayer";
import { PageTourLayer } from "./PageTourLayer";
import { useFirstRun } from "./firstRunStub";
import { userKeyOf } from "./storage";

export default function FirstRunTourLayer() {
  const app = useApp();
  const firstRun = useFirstRun();
  const identity = useSyncExternalStore(session.subscribe, session.getState, session.getState);
  return firstRun === true ? (
    <PageTourLayer page={app.page} firstRun userKey={userKeyOf(identity)} />
  ) : (
    <OnboardingLayer {...(firstRun === false ? { enabled: false } : {})} />
  );
}
