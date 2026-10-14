// OLD-UI-OUT wave 3: the person's own meetings and pinboard items, read-only, as the old Meetings and Pinboards
// screens showed them live (`GET /v1/meetings`, `GET /v1/pinboards`; ADR-0016, FR-PB-01). Same honest states as
// there: loading, a failed read with Try again, "No ... yet", and a note when more exist than the list holds.
// A demo session or a build with no API has no lists, so nothing is drawn.
import { useEffect, useMemo, useState } from "react";
import { API_URL, appCheckToken, authToken, sessionView } from "../../../api/ClientProvider";
import { HttpClient } from "../../../api/http";
import { type PeopleList, peopleListsApi } from "../../api/live/peopleLists";

type Kind = "meetings" | "pinboards";
type State = PeopleList | "loading" | "failed";

const TITLE: Record<Kind, string> = { meetings: "Meetings", pinboards: "Pinboards" };
const EMPTY: Record<Kind, string> = {
  meetings: "No meetings yet.",
  pinboards: "No pinboard items yet.",
};
const READ = { meetings: "getMeetings", pinboards: "getPinboards" } as const;
const cap = (s: string): string => (s[0] ?? "").toUpperCase() + s.slice(1);

function List({ kind, api }: { kind: Kind; api: ReturnType<typeof peopleListsApi> }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<State>("loading");
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt is the explicit retry trigger.
  useEffect(() => {
    let live = true;
    setState("loading");
    api[READ[kind]]().then(
      (reply) => live && setState(reply.data),
      () => live && setState("failed"),
    );
    return () => {
      live = false;
    };
  }, [api, kind, attempt]);
  return (
    <section
      aria-label={TITLE[kind]}
      className="park-agenda-state park-agenda-peoplelist"
      data-testid={`agenda-${kind}`}
    >
      <h2>{TITLE[kind]}</h2>
      {state === "loading" ? (
        <output>Loading…</output>
      ) : state === "failed" ? (
        <div role="alert">
          <p>Could not load this list.</p>
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : state.rows.length === 0 ? (
        <p>{EMPTY[kind]}</p>
      ) : (
        <>
          <ul>
            {state.rows.map((row) => (
              <li key={row.id}>
                <strong>{row.title}</strong>
                <p>
                  {row.scope ? `${row.scope} · ` : ""}
                  {cap(row.status)} · {row.at}
                </p>
                {row.body ? <p>{row.body}</p> : null}
              </li>
            ))}
          </ul>
          {state.truncated ? <p>More items are available than this view can show.</p> : null}
        </>
      )}
    </section>
  );
}

export function PeopleLists() {
  const demo = sessionView.demo();
  const api = useMemo(
    () =>
      API_URL?.trim() && !demo
        ? peopleListsApi(new HttpClient({ baseUrl: API_URL, appCheckToken, authToken }))
        : null,
    [demo],
  );
  if (!api) return null;
  return (
    <>
      <List kind="meetings" api={api} />
      <List kind="pinboards" api={api} />
    </>
  );
}
