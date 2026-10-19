import type { ReactNode } from "react";
import { agenda, gbp, ledger, skills, team } from "../api/fixtures";
import { type AppCtx, PAGE_LABEL } from "../app/AppCtx";
import { PageSheet } from "../components";
import { SampleBadge } from "./SampleBadge";
import "./firstRunPanels.css";

export type PreviewPage = "agenda" | "skills" | "ledger" | "team";
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="park-first-run-card">
      <h2>
        {title}
        <SampleBadge />
      </h2>
      {children}
    </section>
  );
}
/** `embedded` (JUDGE-FIRST-RUN F4): the page's real content is already on screen, so the recorded examples sit below it
 * under their own smaller heading and add no page title or landmark of their own. */
export function FirstRunPanels({
  page,
  app,
  embedded = false,
}: { page: PreviewPage; app: AppCtx; embedded?: boolean }) {
  const explain = () => app.toast("This is sample data. Nothing is saved, sent or charged.");
  return (
    <div data-first-run-panels={page} {...(embedded ? {} : { "data-testid": `park-page-${page}` })}>
      <PageSheet gap={22}>
        <header>
          {embedded ? <h2>Recorded examples</h2> : <h1 tabIndex={-1}>{PAGE_LABEL[page]}</h1>}
          <p>
            {embedded
              ? "Sample data to explore while you have no work yet. These are not your work."
              : "Recorded examples to explore before your first run. These are not your work."}
          </p>
        </header>
        <div className="park-first-run-grid">
          {page === "agenda" && (
            <>
              <Panel title="Events">
                <ul>
                  {agenda.events
                    .filter((e) => e.d === agenda.today)
                    .slice(0, 4)
                    .map((e) => (
                      <li key={e.id}>
                        <strong>{e.t}</strong>
                        <span>{`${Math.floor(e.s)}:${Math.round((e.s % 1) * 60)
                          .toString()
                          .padStart(2, "0")}`}</span>
                      </li>
                    ))}
                </ul>
              </Panel>
              <Panel title="Pins and board">
                <ul>
                  {agenda.pins.slice(0, 4).map((p) => (
                    <li key={p.id}>
                      <strong>{p.title}</strong>
                      <span>
                        {p.board === "team" ? "Team board" : "Personal board"} · {p.note}
                      </span>
                    </li>
                  ))}
                </ul>
              </Panel>
            </>
          )}
          {page === "skills" &&
            skills
              .filter((s) => s.st !== "draft")
              .slice(0, 3)
              .map((s) => (
                <Panel key={s.id} title={s.name}>
                  <p>
                    {s.runs} recorded sample runs · {s.rate}% in this example
                  </p>
                  <p>
                    Run history:{" "}
                    {ledger.runs
                      .find((r) => r[3] === s.id)?.[1]
                      .slice(-4)
                      .map(gbp)
                      .join(" → ") ?? "No recorded example"}
                  </p>
                  <ol>
                    {s.steps.slice(0, 3).map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                </Panel>
              ))}
          {page === "ledger" && (
            <>
              <Panel title="Spend over time">
                <p>{gbp(ledger.spent)} in this example month</p>
                <svg viewBox="0 0 300 80" role="img" aria-label="Sample daily spend">
                  <polyline
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    points={ledger.daily
                      .map(
                        (v, i) =>
                          `${(i * 300) / (ledger.daily.length - 1)},${75 - (v / Math.max(...ledger.daily)) * 65}`,
                      )
                      .join(" ")}
                  />
                </svg>
                <p>Each point is a recorded sample day.</p>
              </Panel>
              <Panel title="Costs per run">
                <ul>
                  {ledger.runs.slice(0, 3).map((r) => (
                    <li key={r[3]}>
                      <strong>{r[0]}</strong>
                      <span>{r[1].map(gbp).join(" → ")}</span>
                    </li>
                  ))}
                </ul>
              </Panel>
              <Panel title="Approval waits">
                <ul>
                  {ledger.waits.buckets.map(([label, count]) => (
                    <li key={label}>
                      <strong>{label}</strong>
                      <span>{count} sample approvals</span>
                    </li>
                  ))}
                </ul>
              </Panel>
            </>
          )}
          {page === "team" && (
            <Panel title="Fictional people">
              <ul>
                {team.people.slice(0, 5).map((p) => (
                  <li key={p.id}>
                    <strong>Fictional {p.name}</strong>
                    <span>
                      {p.dept} · {p.role} in this example
                    </span>
                  </li>
                ))}
              </ul>
              <p>No invitations are sent and these people are not in your workspace.</p>
            </Panel>
          )}
        </div>
        <button className="park-first-run-explain" type="button" onClick={explain}>
          About this sample data
        </button>
      </PageSheet>
    </div>
  );
}
