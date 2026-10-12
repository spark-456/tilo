import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { API_URL, appCheckToken, authToken, sessionView } from "../api/ClientProvider";
import { HttpClient } from "../api/http";
import { session } from "../auth/session";
import { type PeopleList, peopleListFromReply } from "../park/api/live/peopleLists";
import { Page } from "../screens/kit";
const userId = (v: unknown): v is string =>
  typeof v === "string" && /^u_[A-Za-z0-9_]{1,48}$/.test(v);
export function LivePins() {
  const auth = useSyncExternalStore(session.subscribe, session.getState);
  const demo = sessionView.demo();
  const http = useMemo(
    () =>
      API_URL?.trim() && !demo
        ? new HttpClient({ baseUrl: API_URL, appCheckToken, authToken })
        : null,
    [demo],
  );
  const [list, setList] = useState<PeopleList | null>(null);
  const [caller, setCaller] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, retry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const form = useRef<HTMLFormElement>(null);
  const generation = useRef(0);
  const full = auth.status === "google";
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt explicitly retries the read.
  useEffect(() => {
    const current = ++generation.current;
    setList(null);
    setCaller(null);
    setFailed(false);
    setError("");
    if (!http) return;
    void http
      .getJson("/v1/pinboards")
      .then((reply) => {
        const got = peopleListFromReply(reply, "pinboards");
        if (current === generation.current) setList(got);
      })
      .catch(() => {
        if (current === generation.current) setFailed(true);
      });
    if (full)
      void http
        .getJson("/v1/plate")
        .then((reply) => {
          if (
            reply &&
            typeof reply === "object" &&
            "user" in reply &&
            userId(reply.user) &&
            current === generation.current
          )
            setCaller(reply.user);
        })
        .catch(() => {});
    return () => {
      generation.current++;
    };
  }, [http, full, attempt]);
  const writable = !!http && full && !!caller && !!list;
  async function write(body: unknown, id?: string) {
    if (!writable || pending.current || !http) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const current = generation.current;
    try {
      const reply = await http.postJson(
        id ? `/v1/pinboards/${encodeURIComponent(id)}/delete` : "/v1/pinboards",
        body,
      );
      if (
        !reply ||
        typeof reply !== "object" ||
        !("status" in reply) ||
        reply.status !== (id ? "removed" : "active") ||
        !("id" in reply) ||
        (id && reply.id !== id)
      )
        throw Error();
      const got = peopleListFromReply({ items: [reply], truncated: false }, "pinboards");
      const added = got.rows[0];
      if (!id && (!added || (added.personalUser ?? added.setter) !== caller)) throw Error();
      if (current === generation.current && list) {
        const rows = list.rows.filter((row) => row.id !== (id ?? added?.id));
        setList({ ...list, rows: added ? [...rows, added] : rows });
        if (id) form.current?.focus();
      }
    } catch {
      if (current === generation.current)
        setError("Could not confirm the change. Refresh the list before trying again.");
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  return (
    <Page testid="pinboards" title="Pinboards" sub="Recorded pins you can read and manage.">
      {!http ? (
        <p>Not available yet</p>
      ) : failed ? (
        <div role="alert">
          <p>Could not load this list.</p>
          <button type="button" onClick={() => retry((n) => n + 1)}>
            Try again
          </button>
        </div>
      ) : !list ? (
        <output>Loading…</output>
      ) : (
        <>
          {!writable && <p>This list is read only. Your write identity could not be verified.</p>}
          {writable && (
            <form
              ref={form}
              tabIndex={-1}
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                const team =
                  data.get("scope") === "team" ? String(data.get("team") ?? "").trim() : null;
                if (!data.get("scope") || (team !== null && !/^tm_[a-z0-9_]{1,48}$/.test(team))) {
                  setError("Choose a board and enter a valid team ID for a team pin.");
                  return;
                }
                void write({
                  title: String(data.get("title")).trim(),
                  body: String(data.get("body") ?? "").trim() || null,
                  kind: data.get("kind"),
                  url: String(data.get("url") ?? "").trim() || null,
                  ...(team ? { team } : {}),
                });
              }}
            >
              <fieldset disabled={busy} className="pb-draft">
                <legend>Add a pin</legend>
                <label className="field">
                  Title
                  <input name="title" required maxLength={1000} />
                </label>
                <label className="field">
                  Link
                  <input name="url" type="url" maxLength={1000} />
                </label>
                <label className="field">
                  Team ID (for team board)
                  <input name="team" pattern="tm_[a-z0-9_]{1,48}" />
                </label>
                <label className="field">
                  Body
                  <textarea name="body" maxLength={1000} rows={3} />
                </label>
                <label className="field">
                  Kind
                  <select name="kind" style={{ minHeight: 44 }}>
                    <option value="note">Note</option>
                    <option value="decision">Decision</option>
                    <option value="deadline">Deadline</option>
                    <option value="link">Link</option>
                  </select>
                </label>
                <label className="field">
                  Board
                  <select name="scope" required defaultValue="" style={{ minHeight: 44 }}>
                    <option value="" disabled>
                      Choose a board
                    </option>
                    <option value="personal">Personal</option>
                    <option value="team">Team</option>
                  </select>
                </label>
                <p>Team pins require current membership.</p>
                <button type="submit" className="primary" disabled={busy}>
                  {busy ? "Saving…" : "Add pin"}
                </button>
              </fieldset>
            </form>
          )}
          <p>Moving pins is not available yet.</p>
          {error && (
            <div role="alert">
              <p>{error}</p>
              <button type="button" disabled={busy} onClick={() => retry((n) => n + 1)}>
                Refresh list
              </button>
            </div>
          )}
          {list.truncated && <p>More items are available than this view can show.</p>}
          {list.rows.length === 0 ? (
            <p>No pinboard items yet.</p>
          ) : (
            <ul className="blist">
              {list.rows.map((row) => (
                <li className="bitem" key={row.id}>
                  <div className="bitem-main">
                    <b>{row.title}</b>
                    <p>
                      {row.scope} · {row.status} · {row.at}
                    </p>
                    {row.body && <p>{row.body}</p>}
                    {writable &&
                      (row.personalUser ? row.personalUser === caller : row.setter === caller) && (
                        <button
                          type="button"
                          className="secondary"
                          disabled={busy}
                          aria-label={`Delete: ${row.title}`}
                          onClick={() => void write({}, row.id)}
                        >
                          Delete
                        </button>
                      )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Page>
  );
}
