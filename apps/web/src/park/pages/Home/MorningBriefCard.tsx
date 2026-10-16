import { useEffect, useState } from "react";
import { TiloApiError } from "../../../api/http";
import type { BriefSource, MorningBrief, MorningBriefApi } from "../../api/live/morningBrief";

type Read =
  | { kind: "loading" }
  | { kind: "ready"; brief: MorningBrief }
  | { kind: "waiting"; time: string }
  | { kind: "error" };
const sourceLabel = (s: BriefSource) =>
  ({
    calendar_event: "meeting",
    mail: "mail",
    work_item: "work item",
    pinboard_item: "pin",
    world: "world",
  })[s.kind];

export function MorningBriefCard({
  api,
  onOpenSource,
}: {
  api: MorningBriefApi;
  onOpenSource?: (source: BriefSource) => void;
}) {
  const [read, setRead] = useState<Read>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [adding, setAdding] = useState<number | null>(null);
  const [added, setAdded] = useState<number[]>([]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt explicitly retries the read.
  useEffect(() => {
    let active = true;
    setRead({ kind: "loading" });
    api.read().then(
      (brief) => active && setRead({ kind: "ready", brief }),
      async (reason: unknown) => {
        if (!active) return;
        if (reason instanceof TiloApiError && reason.status === 404) {
          try {
            const settings = await api.settings();
            if (active) setRead({ kind: "waiting", time: settings.time });
          } catch {
            if (active) setRead({ kind: "error" });
          }
        } else setRead({ kind: "error" });
      },
    );
    return () => {
      active = false;
    };
  }, [api, attempt]);

  const make = async () => {
    setBusy(true);
    setError("");
    try {
      const brief = await api.make();
      setRead({ kind: "ready", brief });
      setAdded([]);
    } catch (reason) {
      setError(
        reason instanceof TiloApiError && reason.status === 429
          ? "You have made three briefs today. Try again tomorrow."
          : "Could not make your brief. Check before trying again.",
      );
    } finally {
      setBusy(false);
    }
  };
  const add = async (index: number, todo: MorningBrief["todo_suggestions"][number]) => {
    setAdding(index);
    setError("");
    try {
      await api.addTodo(todo);
      setAdded((prev) => [...prev, index]);
    } catch {
      setError("Could not confirm the to-do. Check your work items before trying again.");
    } finally {
      setAdding(null);
    }
  };
  const cite = (source: BriefSource) =>
    onOpenSource ? (
      <button
        type="button"
        key={`${source.kind}:${source.id}`}
        onClick={() => onOpenSource(source)}
      >
        {sourceLabel(source)} · {source.id}
      </button>
    ) : (
      <span key={`${source.kind}:${source.id}`}>
        {sourceLabel(source)} · {source.id}
      </span>
    );

  return (
    <section aria-label="Morning brief" className="park-home-panel park-home-brief">
      <header className="park-home-brief__head">
        <div>
          <h2 className="park-home-h2">Morning brief</h2>
          <p>Your own day at a glance</p>
        </div>
        <button type="button" disabled={busy} onClick={() => void make()}>
          {busy ? "Making your brief…" : "Make it now"}
        </button>
      </header>
      {read.kind === "loading" ? <output>Loading your brief…</output> : null}
      {read.kind === "waiting" ? (
        <p>Your brief arrives at {read.time}. You can make it now.</p>
      ) : null}
      {read.kind === "error" ? (
        <p>
          Could not load your brief.{" "}
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </p>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      {read.kind === "ready" ? (
        <>
          <p>Generated {new Date(read.brief.generated_at).toLocaleString()}</p>
          <section aria-label="Meetings">
            <h3>Meetings</h3>
            {read.brief.meetings.status === "not_connected" ? (
              <p>Connect your calendar to see meetings.</p>
            ) : read.brief.meetings.status === "unavailable" ? (
              <p>Could not read your calendar today.</p>
            ) : read.brief.meetings.items.length ? (
              <ul>
                {read.brief.meetings.items.map((item) => (
                  <li key={item.source.id}>
                    {item.title} · {item.start}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No meetings on this calendar today.</p>
            )}
          </section>
          <section aria-label="Mail">
            <h3>
              {read.brief.mail_needing_reply.status === "unsorted"
                ? "Unread mail"
                : "Mail needing a reply"}
            </h3>
            {read.brief.mail_needing_reply.status === "not_connected" ? (
              <p>Connect your mail to see messages.</p>
            ) : read.brief.mail_needing_reply.status === "unavailable" ? (
              <p>Could not read your mail today.</p>
            ) : read.brief.mail_needing_reply.items.length ? (
              <ul>
                {read.brief.mail_needing_reply.items.map((item) => (
                  <li key={item.source.id}>
                    {item.from_name ?? "Sender unknown"} · {item.subject ?? "No subject"}
                  </li>
                ))}
              </ul>
            ) : (
              <p>
                {read.brief.mail_needing_reply.status === "unsorted"
                  ? "No unread mail in this brief."
                  : "No messages selected for reply."}
              </p>
            )}
          </section>
          <section aria-label="Deadlines">
            <h3>Deadlines</h3>
            {read.brief.deadlines.status === "unavailable" ? (
              <p>Could not read deadlines today.</p>
            ) : read.brief.deadlines.items.length ? (
              <ul>
                {read.brief.deadlines.items.map((item) => (
                  <li key={item.source.id}>
                    {item.title} · {item.due}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No deadlines in this brief.</p>
            )}
          </section>
          {read.brief.suggestions.length ? (
            <section aria-label="Suggestions">
              <h3>Suggestions</h3>
              <ul>
                {read.brief.suggestions.map((s, i) => (
                  <li key={`${i}:${s.text}`}>
                    {s.text}
                    <div className="park-home-brief__cites">{s.cites.map(cite)}</div>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {read.brief.todo_suggestions.length ? (
            <section aria-label="To-do suggestions">
              <h3>To-do suggestions</h3>
              <ul>
                {read.brief.todo_suggestions.map((todo, i) => (
                  <li key={`${i}:${todo.title}`}>
                    {todo.title}
                    {todo.due_text ? ` · ${todo.due_text}` : ""} ·{" "}
                    {todo.mail.subject ?? "No subject"}
                    {added.includes(i) ? (
                      <span>Added to your work items</span>
                    ) : (
                      <button
                        type="button"
                        disabled={adding !== null}
                        onClick={() => void add(i, todo)}
                      >
                        {adding === i ? "Adding…" : "Add to-do"}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
