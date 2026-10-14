import { useEffect, useState } from "react";
import { type HttpClient, TiloApiError } from "../api/http";
import { Page, Section } from "../screens/kit";
import { PLATE_GROUPS, type PlateView, plateFromReply } from "./plateFromReply";

/** FR-PA-02/03: only server reads here. Sample actions are never applied to live rows. */
export function LivePlate({ client }: { client: HttpClient }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PlateView | "loading" | "failed" | "empty">("loading");
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt is the explicit retry trigger.
  useEffect(() => {
    let current = true;
    setState("loading");
    void client
      .getJson("/v1/plate")
      .then((reply) => {
        const plate = plateFromReply(reply);
        if (!plate) throw new TiloApiError("Unreadable plate reply", 200, true);
        if (current) setState(plate);
      })
      .catch((error: unknown) => {
        // PE-26: no People record means no plate yet; other failures remain retryable UI errors.
        if (current)
          setState(error instanceof TiloApiError && error.status === 404 ? "empty" : "failed");
      });
    return () => {
      current = false;
    };
  }, [client, attempt]);
  return (
    <Page testid="my-plate" title="My plate" sub="What is waiting on you, in one place.">
      {state === "loading" ? (
        <output>Loading your plate…</output>
      ) : state === "failed" ? (
        <div role="alert">
          <p>Could not load your plate. Try again.</p>
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : state === "empty" ? (
        <p>Nothing on your plate yet.</p>
      ) : (
        <>
          <p>As of {state.asOf}</p>
          {state.truncated ? <p>More items are available than this view can show.</p> : null}
          {state.rows.length === 0 ? (
            <p>Nothing on your plate yet.</p>
          ) : (
            <p>Item actions are not available here yet.</p>
          )}
          {Object.entries(PLATE_GROUPS).map(([group, title]) => {
            const rows = state.rows.filter((r) => r.group === group);
            return rows.length ? (
              <Section key={group} title={title}>
                <ul className="blist">
                  {rows.map((r) => (
                    <li className="bitem" key={r.key}>
                      <div className="bitem-main">
                        <b>{r.title || "Title not available yet"}</b>
                        {r.due ? <p>Due {r.due}</p> : null}
                        {r.at ? <p>{r.at}</p> : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </Section>
            ) : null;
          })}
        </>
      )}
    </Page>
  );
}
