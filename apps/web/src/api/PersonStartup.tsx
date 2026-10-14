// QA-4 / FR-TEAM-01: settle founding before first-load consumers mount.
import { type ReactNode, useEffect, useState } from "react";
import type { HttpClient } from "./http";

export function PersonStartup({
  http,
  children,
}: {
  readonly http: Pick<HttpClient, "getJson">;
  readonly children: ReactNode;
}) {
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    let active = true;
    // The shared people reader creates only on 404 and retains uncertain attempts.
    // Refusal/failure leaves consumers to show their existing honest setup/error state.
    void http
      .getJson("/v1/people")
      .catch(() => undefined)
      .then(() => {
        if (active) setSettled(true);
      });
    return () => {
      active = false;
    };
  }, [http]);
  return settled ? <>{children}</> : <output>Getting your organisation ready…</output>;
}
