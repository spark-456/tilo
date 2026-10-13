import { useEffect, useMemo, useState } from "react";
import { API_URL, appCheckToken, authToken, sessionView } from "../api/ClientProvider";
import { HttpClient } from "../api/http";
import type { PeopleList } from "../park/api/live/peopleLists";
import { peopleListsApi } from "../park/api/liveApi";
import { Page } from "../screens/kit";

export function LiveLists({ kind }: { kind: "meetings" | "pinboards" }) {
  const demo = sessionView.demo();
  const api = useMemo(
    () =>
      API_URL?.trim() && !demo
        ? peopleListsApi(new HttpClient({ baseUrl: API_URL, appCheckToken, authToken }))
        : null,
    [demo],
  );
  const [attempt, retry] = useState(0);
  const [state, setState] = useState<PeopleList | "loading" | "failed">("loading");
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt is the explicit retry trigger.
  useEffect(() => {
    if (!api) return;
    let active = true;
    setState("loading");
    void (kind === "meetings" ? api.getMeetings() : api.getPinboards())
      .then((reply) => {
        if (active) setState(reply.data);
      })
      .catch(() => {
        if (active) setState("failed");
      });
    return () => {
      active = false;
    };
  }, [api, kind, attempt]);
  return (
    <Page
      testid={kind}
      title={kind === "meetings" ? "Meetings" : "Pinboards"}
      sub="Recorded items you can read."
    >
      {!api ? (
        <p>Not available yet</p>
      ) : state === "loading" ? (
        <output>Loading…</output>
      ) : state === "failed" ? (
        <div role="alert">
          <p>Could not load this list.</p>
          <button type="button" onClick={() => retry((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : (
        <>
          {state.truncated && <p>More items are available than this view can show.</p>}
          {state.rows.length === 0 ? (
            <p>{kind === "meetings" ? "No meetings yet" : "No pinboard items yet"}.</p>
          ) : (
            <>
              <p>This list is read only.</p>
              <ul className="blist">
                {state.rows.map((row) => (
                  <li className="bitem" key={row.id}>
                    <div className="bitem-main">
                      <b>{row.title}</b>
                      <p>
                        {row.scope ? `${row.scope} · ` : ""}
                        {row.status[0]?.toUpperCase()}
                        {row.status.slice(1)} · {row.at}
                      </p>
                      {row.body && <p>{row.body}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Page>
  );
}
