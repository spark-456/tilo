import type { ReactNode } from "react";
import { agenda, decisions, gbp, ledger, worlds } from "../api/fixtures";
import type { AppCtx } from "../app/AppCtx";
import { SampleBadge } from "./SampleBadge";
import "./firstRunPanels.css";
import "./firstRunOverview.css";

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="park-first-run-card">
      <h2>
        {title} <SampleBadge />
      </h2>
      {children}
    </section>
  );
}
/** Examples are presentation only: they never enter the store, API or personal totals. */
export function FirstRunOverview({ page, app }: { page: "home" | "worlds"; app: AppCtx }) {
  const examples = worlds();
  const explain = () => app.toast("This is sample data. Nothing is saved, sent or charged.");
  return (
    <section className="park-first-run-overview" data-first-run-overview={page}>
      {page === "home" ? <h1 tabIndex={-1}>Home</h1> : <h2>Explore the scales of work</h2>}
      <p>Recorded examples before your first run. These are not your work.</p>
      <div className="park-first-run-grid">
        {page === "home" ? (
          <>
            <Panel title="Needs you">
              <ul>
                {decisions.map((d) => (
                  <li key={d.k}>
                    <strong>{d.title}</strong>
                    <span>{d.body}</span>
                  </li>
                ))}
              </ul>
            </Panel>
            <Panel title="Live now">
              <p>Recorded activity in this example; no agents are running here.</p>
              <ul>
                {examples
                  .filter((w) => w.st === "running" || w.st === "needs")
                  .slice(0, 3)
                  .map((w) => (
                    <li key={w.id}>
                      <strong>{w.name}</strong>
                      <span>
                        {w.tier} · {w.prog ?? 0}% in the recording
                      </span>
                    </li>
                  ))}
              </ul>
            </Panel>
            <Panel title="Up next">
              <ul>
                {agenda.events
                  .filter((e) => e.d === agenda.today)
                  .slice(0, 3)
                  .map((e) => (
                    <li key={e.id}>
                      <strong>{e.t}</strong>
                      <span>Recorded sample calendar</span>
                    </li>
                  ))}
              </ul>
            </Panel>
            <Panel title="Spend">
              <p>{gbp(ledger.spent)} in this example month</p>
              <p>Recorded sample costs. Nothing was charged to your account.</p>
            </Panel>
          </>
        ) : (
          (["City", "Town", "Village"] as const).map((tier) => {
            const world = examples.find((w) => w.tier === tier);
            return world ? (
              <Panel key={tier} title={tier}>
                <h3>{world.name}</h3>
                <p>{world.meta ?? world.tool}</p>
                <p>
                  {world.prog ?? 0}% in this recorded example · {world.spend}
                </p>
                <button type="button" className="park-first-run-explain" onClick={explain}>
                  About this sample {tier.toLowerCase()}
                </button>
              </Panel>
            ) : null;
          })
        )}
      </div>
      {page === "home" ? (
        <button type="button" className="park-first-run-explain" onClick={explain}>
          About this sample data
        </button>
      ) : (
        <p>
          Use Show sample project to access its existing recorded player. Hide sample project hides
          it again.
        </p>
      )}
    </section>
  );
}
